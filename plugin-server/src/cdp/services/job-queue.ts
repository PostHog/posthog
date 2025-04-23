// NOTE: We are often experimenting with different job queue implementations.
// To make this easier this class is designed to abstract the queue as much as possible from
// the underlying implementation.

import { CyclotronJob, CyclotronManager, CyclotronWorker } from '@posthog/cyclotron'
import { chunk } from 'lodash'
import { Message } from 'node-rdkafka'
import { Counter, Gauge, Histogram } from 'prom-client'

import { KafkaConsumer } from '../../kafka/batch-consumer-v2'
import { KafkaProducerWrapper, TopicMessage } from '../../kafka/producer'
import { Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import {
    HogFunctionInvocation,
    HogFunctionInvocationJobQueue,
    HogFunctionInvocationResult,
    HogFunctionInvocationSerialized,
} from '../types'
import {
    cyclotronJobToInvocation,
    invocationToCyclotronJobUpdate,
    isLegacyPluginHogFunction,
    serializeHogFunctionInvocation,
} from '../utils'
import { HogFunctionManagerService } from './hog-function-manager.service'

const cyclotronBatchUtilizationGauge = new Gauge({
    name: 'cdp_cyclotron_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['queue'],
})

const counterJobsProcessed = new Counter({
    name: 'cdp_cyclotron_jobs_processed',
    help: 'The number of jobs we are managing to process',
    labelNames: ['queue'],
})

const histogramCyclotronJobsCreated = new Histogram({
    name: 'cdp_cyclotron_jobs_created_per_batch',
    help: 'The number of jobs we are creating in a single batch',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

export class CyclotronJobQueue {
    private implementation: 'cyclotron' | 'kafka' = 'cyclotron'
    private cyclotronWorker?: CyclotronWorker
    private cyclotronManager?: CyclotronManager
    private kafkaConsumer?: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper

    constructor(
        private hub: Hub,
        private queue: HogFunctionInvocationJobQueue,
        private hogFunctionManager: HogFunctionManagerService,
        private consumeBatch?: (invocations: HogFunctionInvocation[]) => Promise<any>
    ) {
        this.implementation = this.hub.CDP_CYCLOTRON_DELIVERY_MODE
    }

    /**
     * Helper to only start the producer related code (e.g. when not a consumer)
     */
    public async startAsProducer() {
        if (this.implementation === 'cyclotron') {
            await this.startCyclotronManager()
        } else {
            await this.startKafkaProducer()
        }
    }

    public async start() {
        if (!this.consumeBatch) {
            throw new Error('consumeBatch is required to start the job queue')
        }
        if (this.implementation === 'cyclotron') {
            await this.startCyclotronWorker()
        } else {
            await this.startKafkaProducer()
            await this.startKafkaConsumer()
        }
    }

    public async stop() {
        await this.cyclotronWorker?.disconnect()
    }

    public isHealthy() {
        if (this.implementation === 'cyclotron') {
            return this.cyclotronWorker?.isHealthy()
        }
        // TODO: Kafka version
        return true
    }

    public async queueInvocations(invocations: HogFunctionInvocation[]) {
        if (this.implementation === 'cyclotron') {
            await this.createCyclotronJobs(invocations)
        } else {
            await this.createKafkaJobs(invocations)
        }
    }

    public async queueInvocationResults(invocationResults: HogFunctionInvocationResult[]) {
        if (this.implementation === 'cyclotron') {
            await this.updateCyclotronJobs(invocationResults)
        } else {
            await this.updateKafkaJobs(invocationResults)
        }
    }

    // CYCLOTRON

    private async startCyclotronWorker() {
        if (!this.hub.CYCLOTRON_DATABASE_URL) {
            throw new Error('Cyclotron database URL not set! This is required for the CDP services to work.')
        }
        this.cyclotronWorker = new CyclotronWorker({
            pool: {
                dbUrl: this.hub.CYCLOTRON_DATABASE_URL,
            },
            queueName: this.queue,
            // For the fetch queue we never need the state
            includeVmState: this.queue === 'fetch' ? false : true,
            batchMaxSize: this.hub.CDP_CYCLOTRON_BATCH_SIZE,
            pollDelayMs: this.hub.CDP_CYCLOTRON_BATCH_DELAY_MS,
            includeEmptyBatches: true,
            shouldCompressVmState: this.hub.CDP_CYCLOTRON_COMPRESS_VM_STATE,
        })
        await this.cyclotronWorker.connect((jobs) => this.consumeCyclotronJobs(jobs))
    }

    private async startCyclotronManager() {
        if (!this.hub.CYCLOTRON_DATABASE_URL) {
            throw new Error('Cyclotron database URL not set! This is required for the CDP services to work.')
        }
        this.cyclotronManager = new CyclotronManager({
            shards: [
                {
                    dbUrl: this.hub.CYCLOTRON_DATABASE_URL,
                },
            ],
            shardDepthLimit: this.hub.CYCLOTRON_SHARD_DEPTH_LIMIT ?? 1000000,
            shouldCompressVmState: this.hub.CDP_CYCLOTRON_COMPRESS_VM_STATE,
            shouldUseBulkJobCopy: this.hub.CDP_CYCLOTRON_USE_BULK_COPY_JOB,
        })

        await this.cyclotronManager.connect()
    }

    private getCyclotronWorker(): CyclotronWorker {
        if (!this.cyclotronWorker) {
            throw new Error('CyclotronWorker not initialized')
        }
        return this.cyclotronWorker
    }

    private getCyclotronManager(): CyclotronManager {
        if (!this.cyclotronManager) {
            throw new Error('CyclotronManager not initialized')
        }
        return this.cyclotronManager
    }

    private async createCyclotronJobs(invocations: HogFunctionInvocation[]) {
        const cyclotronManager = this.getCyclotronManager()

        // For the cyclotron ones we simply create the jobs
        const cyclotronJobs = invocations.map((item) => {
            return {
                teamId: item.globals.project.id,
                functionId: item.hogFunction.id,
                queueName: isLegacyPluginHogFunction(item.hogFunction) ? 'plugin' : 'hog',
                priority: item.queuePriority,
                vmState: serializeHogFunctionInvocation(item),
            }
        })

        try {
            histogramCyclotronJobsCreated.observe(cyclotronJobs.length)
            // Cyclotron batches inserts into one big INSERT which can lead to contention writing WAL information hence we chunk into batches

            const chunkedCyclotronJobs = chunk(cyclotronJobs, this.hub.CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE)

            if (this.hub.CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES) {
                // NOTE: It's not super clear the perf tradeoffs of doing this in parallel hence the config option
                await Promise.all(chunkedCyclotronJobs.map((jobs) => cyclotronManager.bulkCreateJobs(jobs)))
            } else {
                for (const jobs of chunkedCyclotronJobs) {
                    await cyclotronManager.bulkCreateJobs(jobs)
                }
            }
        } catch (e) {
            logger.error('⚠️', 'Error creating cyclotron jobs', e)
            logger.warn('⚠️', 'Failed jobs', { jobs: cyclotronJobs })
            throw e
        }
    }

    private async consumeCyclotronJobs(jobs: CyclotronJob[]) {
        const worker = this.getCyclotronWorker()
        cyclotronBatchUtilizationGauge
            .labels({ queue: this.queue })
            .set(jobs.length / this.hub.CDP_CYCLOTRON_BATCH_SIZE)

        const invocations: HogFunctionInvocation[] = []
        // A list of all the promises related to job releasing that we need to await
        const failReleases: Promise<void>[] = []

        const hogFunctionIds: string[] = []

        for (const job of jobs) {
            if (!job.functionId) {
                throw new Error('Bad job: ' + JSON.stringify(job))
            }

            hogFunctionIds.push(job.functionId)
        }

        const hogFunctions = await this.hogFunctionManager.getHogFunctions(hogFunctionIds)

        for (const job of jobs) {
            // NOTE: This is all a bit messy and might be better to refactor into a helper
            const hogFunction = hogFunctions[job.functionId!]

            if (!hogFunction) {
                // Here we need to mark the job as failed

                logger.error('⚠️', 'Error finding hog function', {
                    id: job.functionId,
                })
                worker.updateJob(job.id, 'failed')
                failReleases.push(worker.releaseJob(job.id))
                continue
            }

            const invocation = cyclotronJobToInvocation(job, hogFunction)
            invocations.push(invocation)
        }

        await Promise.all([this.consumeBatch!(invocations), ...failReleases])

        counterJobsProcessed.inc({ queue: this.queue }, jobs.length)
    }

    private async updateCyclotronJobs(invocationResults: HogFunctionInvocationResult[]) {
        const worker = this.getCyclotronWorker()
        await Promise.all(
            invocationResults.map(async (item) => {
                const id = item.invocation.id
                if (item.error) {
                    logger.debug('⚡️', 'Updating job to failed', id)
                    worker.updateJob(id, 'failed')
                } else if (item.finished) {
                    logger.debug('⚡️', 'Updating job to completed', id)
                    worker.updateJob(id, 'completed')
                } else {
                    logger.debug('⚡️', 'Updating job to available', id)

                    const updates = invocationToCyclotronJobUpdate(item.invocation)

                    if (this.queue === 'fetch') {
                        // When updating fetch jobs, we don't want to include the vm state
                        updates.vmState = undefined
                    }

                    worker.updateJob(id, 'available', updates)
                }
                return worker.releaseJob(id)
            })
        )
    }

    // KAFKA

    private getKafkaProducer(): KafkaProducerWrapper {
        if (!this.kafkaProducer) {
            throw new Error('KafkaProducer not initialized')
        }
        return this.kafkaProducer
    }

    private async startKafkaConsumer() {
        const groupId = `cdp-cyclotron-${this.queue}-consumer`
        const topic = `cdp-cyclotron-${this.queue}`

        // TODO: All of this
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic, callEachBatchWhenEmpty: true })

        await this.kafkaConsumer.connect(async (messages) => {
            await this.consumeKafkaBatch(messages)
        })
    }

    private async startKafkaProducer() {
        // TODO: This tbh
        this.kafkaProducer = await KafkaProducerWrapper.create({})
    }

    private async createKafkaJobs(invocations: HogFunctionInvocation[]) {
        const producer = this.getKafkaProducer()
        const payload: TopicMessage = {
            topic: `cdp-cyclotron-${this.queue}`,
            messages: invocations.map((x) => {
                const serialized = serializeHogFunctionInvocation(x)
                // NOTE: Should we compress this already?
                return {
                    value: JSON.stringify(serialized),
                    key: x.id,
                    headers: {
                        hogFunctionId: x.hogFunction.id,
                        teamId: x.globals.project.id.toString(),
                    },
                }
            }),
        }

        await producer.queueMessages(payload)
    }

    private async updateKafkaJobs(invocationResults: HogFunctionInvocationResult[]) {
        // With kafka we are essentially re-queuing the work to the target topic if it isn't finished
        const invocations = invocationResults.reduce((acc, res) => {
            if (res.finished) {
                return acc
            }

            return [...acc, res.invocation]
        }, [] as HogFunctionInvocation[])

        await this.createKafkaJobs(invocations)
    }

    private async consumeKafkaBatch(messages: Message[]) {
        cyclotronBatchUtilizationGauge
            .labels({ queue: this.queue })
            .set(messages.length / this.hub.CDP_CYCLOTRON_BATCH_SIZE)

        const invocations: HogFunctionInvocation[] = []
        const hogFunctionIds = new Set<string>()

        messages.forEach((message) => {
            message.headers?.forEach((header) => {
                if (header.key === 'hogFunctionId' && header.value) {
                    hogFunctionIds.add(header.value.toString())
                }
            })
        })

        const hogFunctions = await this.hogFunctionManager.getHogFunctions(Array.from(hogFunctionIds))

        // Parse all the messages into invocations
        for (const message of messages) {
            if (!message.value) {
                throw new Error('Bad message: ' + JSON.stringify(message))
            }

            const invocationSerialized: HogFunctionInvocationSerialized = parseJSON(message.value.toString() ?? '')

            // NOTE: We might crash out here and thats fine as it would indicate that the schema changed
            // which we have full control over so shouldn't be possible

            const hogFunction = hogFunctions[invocationSerialized.hogFunctionId]

            if (!hogFunction) {
                logger.error('⚠️', 'Error finding hog function', {
                    id: invocationSerialized.hogFunctionId,
                })
                continue
            }

            const invocation: HogFunctionInvocation = {
                ...invocationSerialized,
                hogFunction,
            }

            invocations.push(invocation)
        }

        await this.consumeBatch!(invocations)

        counterJobsProcessed.inc({ queue: this.queue }, invocations.length)
    }
}
