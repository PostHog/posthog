/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */

import {
    CyclotronJob,
    CyclotronJobInit,
    CyclotronJobUpdate,
    CyclotronManager,
    CyclotronWorker,
} from '@posthog/cyclotron'
import { chunk } from 'lodash'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'
import { Counter, Gauge, Histogram } from 'prom-client'

import { KafkaConsumer, parseKafkaHeaders } from '../../kafka/consumer'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { PluginsServerConfig } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import {
    CYCLOTRON_JOB_QUEUE_KINDS,
    CyclotronJobQueueKind,
    HOG_FUNCTION_INVOCATION_JOB_QUEUES,
    HogFunctionInvocation,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionInvocationJobQueue,
    HogFunctionInvocationQueueParameters,
    HogFunctionInvocationResult,
    HogFunctionInvocationSerialized,
    HogFunctionType,
} from '../types'
import { HogFunctionManagerService } from './hog-function-manager.service'

const cyclotronBatchUtilizationGauge = new Gauge({
    name: 'cdp_cyclotron_batch_utilization',
    help: 'Indicates how big batches are we are processing compared to the max batch size. Useful as a scaling metric',
    labelNames: ['queue', 'source'],
})

const counterJobsProcessed = new Counter({
    name: 'cdp_cyclotron_jobs_processed',
    help: 'The number of jobs we are managing to process',
    labelNames: ['queue', 'source'],
})

const histogramCyclotronJobsCreated = new Histogram({
    name: 'cdp_cyclotron_jobs_created_per_batch',
    help: 'The number of jobs we are creating in a single batch',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

export type CyclotronJobQueueRouting = {
    [key: string]: {
        target: CyclotronJobQueueKind
        percentage: number
    }
}

export class CyclotronJobQueue {
    private consumerMode: CyclotronJobQueueKind
    private producerMapping: CyclotronJobQueueRouting
    private cyclotronWorker?: CyclotronWorker
    private cyclotronManager?: CyclotronManager
    private kafkaConsumer?: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper

    constructor(
        private config: PluginsServerConfig,
        private queue: HogFunctionInvocationJobQueue,
        private hogFunctionManager: HogFunctionManagerService,
        private consumeBatch?: (invocations: HogFunctionInvocation[]) => Promise<any>
    ) {
        this.consumerMode = this.config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE
        this.producerMapping = getProducerMapping(this.config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING)

        logger.info('🔄', 'CyclotronJobQueue initialized', {
            consumerMode: this.consumerMode,
            producerMapping: this.producerMapping,
        })
    }

    /**
     * Helper to only start the producer related code (e.g. when not a consumer)
     */
    public async startAsProducer() {
        // We only need to connect to the queue targets that are configured
        const targets = new Set<CyclotronJobQueueKind>(Object.values(this.producerMapping).map((x) => x.target))

        if (targets.has('postgres')) {
            await this.startCyclotronManager()
        }

        if (targets.has('kafka')) {
            await this.startKafkaProducer()
        }
    }

    public async start() {
        if (!this.consumeBatch) {
            throw new Error('consumeBatch is required to start the job queue')
        }
        if (this.consumerMode === 'postgres') {
            await this.startCyclotronWorker()
        } else {
            await this.startKafkaConsumer()
        }

        // The consumer always needs the producers as well
        await this.startAsProducer()
    }

    public async stop() {
        await Promise.all([this.cyclotronWorker?.disconnect(), this.kafkaConsumer?.disconnect()])
    }

    public isHealthy() {
        if (this.consumerMode === 'postgres') {
            return this.getCyclotronWorker().isHealthy()
        } else {
            return this.kafkaConsumer!.isHealthy()
        }
    }

    public async queueInvocations(invocations: HogFunctionInvocation[]) {
        const postgresInvocations: HogFunctionInvocation[] = []
        const kafkaInvocations: HogFunctionInvocation[] = []

        for (const invocation of invocations) {
            const producerConfig = this.producerMapping[invocation.queue] ?? this.producerMapping['*']

            let target = producerConfig.target

            if (producerConfig.percentage < 1) {
                const otherTarget = target === 'postgres' ? 'kafka' : 'postgres'
                target = Math.random() < producerConfig.percentage ? target : otherTarget
            }

            if (target === 'postgres') {
                postgresInvocations.push(invocation)
            } else {
                kafkaInvocations.push(invocation)
            }
        }

        if (postgresInvocations.length > 0) {
            await this.createCyclotronJobs(postgresInvocations)
        }
        if (kafkaInvocations.length > 0) {
            await this.createKafkaJobs(kafkaInvocations)
        }
    }

    public async queueInvocationResults(invocationResults: HogFunctionInvocationResult[]) {
        // TODO: Routing based on queue name is slightly tricky here as postgres jobs need to be acked no matter what...
        // We need to know if the job came from postgres and if so we need to ack, regardless of the target...

        const postgresInvocationsToCreate: HogFunctionInvocationResult[] = []
        const postgresInvocationsToUpdate: HogFunctionInvocationResult[] = []
        const kafkaInvocations: HogFunctionInvocationResult[] = []

        for (const invocationResult of invocationResults) {
            const producerConfig = this.producerMapping[invocationResult.invocation.queue] ?? this.producerMapping['*']

            let target = producerConfig.target

            if (producerConfig.percentage < 1) {
                const otherTarget = target === 'postgres' ? 'kafka' : 'postgres'
                target = Math.random() < producerConfig.percentage ? target : otherTarget
            }

            if (target === 'postgres') {
                if (invocationResult.invocation.queueSource === 'postgres') {
                    postgresInvocationsToUpdate.push(invocationResult)
                } else {
                    postgresInvocationsToCreate.push(invocationResult)
                }
            } else {
                kafkaInvocations.push(invocationResult)
            }
        }

        logger.debug('🔄', 'Queueing postgres invocations', {
            kafka: kafkaInvocations.map(
                (x) => `${x.invocation.id} (queue:${x.invocation.queue},source:${x.invocation.queueSource})`
            ),
            postgres_update: postgresInvocationsToUpdate.map(
                (x) => `${x.invocation.id} (queue:${x.invocation.queue},source:${x.invocation.queueSource})`
            ),
            postgres_create: postgresInvocationsToCreate.map(
                (x) => `${x.invocation.id} (queue:${x.invocation.queue},source:${x.invocation.queueSource})`
            ),
        })

        if (postgresInvocationsToUpdate.length > 0) {
            await this.updateCyclotronJobs(postgresInvocationsToUpdate)
        }

        if (postgresInvocationsToCreate.length > 0) {
            await this.createCyclotronJobs(postgresInvocationsToCreate.map((x) => x.invocation))
        }

        if (kafkaInvocations.length > 0) {
            await this.updateKafkaJobs(kafkaInvocations)

            const jobsToRelease = kafkaInvocations.filter((x) => x.invocation.queueSource === 'postgres')
            if (jobsToRelease.length > 0) {
                await this.releaseCyclotronJobs(jobsToRelease)
            }
        }
    }

    // CYCLOTRON

    private async startCyclotronWorker() {
        if (!this.config.CYCLOTRON_DATABASE_URL) {
            throw new Error('Cyclotron database URL not set! This is required for the CDP services to work.')
        }
        this.cyclotronWorker = new CyclotronWorker({
            pool: {
                dbUrl: this.config.CYCLOTRON_DATABASE_URL,
            },
            queueName: this.queue,
            includeVmState: true, // NOTE: We used to omit the vmstate but given we can requeue to kafka we need it
            batchMaxSize: this.config.CDP_CYCLOTRON_BATCH_SIZE,
            pollDelayMs: this.config.CDP_CYCLOTRON_BATCH_DELAY_MS,
            includeEmptyBatches: true,
            shouldCompressVmState: this.config.CDP_CYCLOTRON_COMPRESS_VM_STATE,
        })
        await this.cyclotronWorker.connect((jobs) => this.consumeCyclotronJobs(jobs))
    }

    private async startCyclotronManager() {
        if (!this.config.CYCLOTRON_DATABASE_URL) {
            throw new Error('Cyclotron database URL not set! This is required for the CDP services to work.')
        }
        this.cyclotronManager = new CyclotronManager({
            shards: [
                {
                    dbUrl: this.config.CYCLOTRON_DATABASE_URL,
                },
            ],
            shardDepthLimit: this.config.CYCLOTRON_SHARD_DEPTH_LIMIT ?? 1000000,
            shouldCompressVmState: this.config.CDP_CYCLOTRON_COMPRESS_VM_STATE,
            shouldUseBulkJobCopy: this.config.CDP_CYCLOTRON_USE_BULK_COPY_JOB,
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
        const cyclotronJobs = invocations.map((item) => invocationToCyclotronJobInitial(item))

        try {
            histogramCyclotronJobsCreated.observe(cyclotronJobs.length)
            // Cyclotron batches inserts into one big INSERT which can lead to contention writing WAL information hence we chunk into batches

            const chunkedCyclotronJobs = chunk(cyclotronJobs, this.config.CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE)

            if (this.config.CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES) {
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
            .labels({ queue: this.queue, source: 'postgres' })
            .set(jobs.length / this.config.CDP_CYCLOTRON_BATCH_SIZE)

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

        counterJobsProcessed.inc({ queue: this.queue, source: 'postgres' }, jobs.length)
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

    private async releaseCyclotronJobs(invocationResults: HogFunctionInvocationResult[]) {
        // Called specially for jobs that came from postgres but are being requeued to kafka
        const worker = this.getCyclotronWorker()
        await Promise.all(
            invocationResults.map(async (item) => {
                const id = item.invocation.id
                logger.debug('⚡️', 'Releasing job', id)
                worker.updateJob(id, 'completed')
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
        const topic = `cdp_cyclotron_${this.queue}`

        // NOTE: As there is only ever one consumer per process we use the KAFKA_CONSUMER_ vars as with any other consumer
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic, callEachBatchWhenEmpty: true })

        logger.info('🔄', 'Connecting kafka consumer', { groupId, topic })
        await this.kafkaConsumer.connect(async (messages) => {
            await this.consumeKafkaBatch(messages)
        })
    }

    private async startKafkaProducer() {
        // NOTE: For producing we use different values dedicated for Cyclotron as this is typically using its own Kafka cluster
        this.kafkaProducer = await KafkaProducerWrapper.create(
            {
                ...this.config,
            },
            'cdp_producer'
        )
    }

    private async createKafkaJobs(invocations: HogFunctionInvocation[]) {
        const producer = this.getKafkaProducer()

        const messages = invocations.map((x) => {
            const serialized = serializeHogFunctionInvocation(x)
            return {
                topic: `cdp_cyclotron_${x.queue}`,
                messages: [
                    {
                        // NOTE: Should we compress this already?
                        value: JSON.stringify(serialized),
                        key: x.id,
                        headers: {
                            hogFunctionId: x.hogFunction.id,
                            teamId: x.globals.project.id.toString(),
                        },
                    },
                ],
            }
        })

        logger.debug('🔄', 'Queueing kafka jobs', { messages })

        await producer.queueMessages(messages)
    }

    private async updateKafkaJobs(invocationResults: HogFunctionInvocationResult[]) {
        // With kafka we are essentially re-queuing the work to the target topic if it isn't finished
        const invocations = invocationResults.reduce((acc, res) => {
            if (res.finished) {
                return acc
            }

            if (res.invocation.queue === 'fetch' && !res.invocation.queueParameters) {
                throw new Error('Fetch job has no queue parameters')
            }

            return [...acc, res.invocation]
        }, [] as HogFunctionInvocation[])

        await this.createKafkaJobs(invocations)
    }

    private async consumeKafkaBatch(messages: Message[]) {
        cyclotronBatchUtilizationGauge
            .labels({ queue: this.queue, source: 'kafka' })
            .set(messages.length / this.config.CDP_CYCLOTRON_BATCH_SIZE)

        if (messages.length === 0) {
            return
        }

        const invocations: HogFunctionInvocation[] = []
        const hogFunctionIds = new Set<string>()

        messages.forEach((message) => {
            const headers = parseKafkaHeaders(message.headers ?? [])
            const hogFunctionId = headers['hogFunctionId']
            if (hogFunctionId) {
                hogFunctionIds.add(hogFunctionId)
            }
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
                queueSource: 'kafka', // NOTE: We always set this here, as we know it came from kafka
            }

            invocations.push(invocation)
        }

        await this.consumeBatch!(invocations)

        counterJobsProcessed.inc({ queue: this.queue, source: 'kafka' }, invocations.length)
    }
}

function serializeHogFunctionInvocation(invocation: HogFunctionInvocation): HogFunctionInvocationSerialized {
    const serializedInvocation: HogFunctionInvocationSerialized = {
        ...invocation,
        hogFunctionId: invocation.hogFunction.id,
    }

    delete (serializedInvocation as any).hogFunction

    return serializedInvocation
}

function serializeHogFunctionInvocationForCyclotron(
    invocation: HogFunctionInvocation
): HogFunctionInvocationSerialized {
    const serializedInvocation = serializeHogFunctionInvocation(invocation)

    // Ensure we don't include this as it is set elsewhere
    delete serializedInvocation.queueParameters

    return serializedInvocation
}

function invocationToCyclotronJobInitial(invocation: HogFunctionInvocation): CyclotronJobInit {
    const queueParameters: HogFunctionInvocation['queueParameters'] = invocation.queueParameters
    let blob: CyclotronJobInit['blob'] = null
    let parameters: CyclotronJobInit['parameters'] = null

    if (queueParameters) {
        const { body, ...rest } = queueParameters
        parameters = rest
        blob = body ? Buffer.from(body) : null
    }

    const job: CyclotronJobInit = {
        teamId: invocation.globals.project.id,
        functionId: invocation.hogFunction.id,
        queueName: invocation.queue,
        priority: invocation.queuePriority,
        vmState: serializeHogFunctionInvocationForCyclotron(invocation),
        parameters,
        blob,
        metadata: invocation.queueMetadata ?? null,
        scheduled: invocation.queueScheduledAt?.toISO() ?? null,
    }
    return job
}

function invocationToCyclotronJobUpdate(invocation: HogFunctionInvocation): CyclotronJobUpdate {
    const job = invocationToCyclotronJobInitial(invocation)
    // Currently the job updates are identical to the initial job
    return job
}

function cyclotronJobToInvocation(job: CyclotronJob, hogFunction: HogFunctionType): HogFunctionInvocation {
    const parsedState = job.vmState as HogFunctionInvocationSerialized | null
    const params = job.parameters as HogFunctionInvocationQueueParameters | undefined

    if (job.blob && params) {
        // Deserialize the blob into the params
        try {
            params.body = job.blob ? Buffer.from(job.blob).toString('utf-8') : undefined
        } catch (e) {
            logger.error('Error parsing blob', e, job.blob)
            captureException(e)
        }
    }

    // TRICKY: If this is being converted for the fetch service we don't deserialize the vmstate as it isn't necessary
    // We cast it to the right type as we would rather things crash if they try to use it
    // This will be fixed in an upcoming PR

    return {
        id: job.id,
        globals: parsedState?.globals ?? ({} as unknown as HogFunctionInvocationGlobalsWithInputs),
        teamId: hogFunction.team_id,
        hogFunction,
        queue: (job.queueName as HogFunctionInvocationJobQueue) ?? 'hog',
        queuePriority: job.priority,
        queueScheduledAt: job.scheduled ? DateTime.fromISO(job.scheduled) : undefined,
        queueMetadata: job.metadata ?? undefined,
        queueParameters: params,
        queueSource: 'postgres', // NOTE: We always set this here, as we know it came from postgres
        vmState: parsedState?.vmState,
        timings: parsedState?.timings ?? [],
    }
}

/**
 * Parses a mapping config from a string into a routing object.
 * Format is like `QUEUE:TARGET:PERCENTAGE with percentage being optional and defaulting to 100
 *
 * So for example `*:kafka:10,fetch:postgres` would result in all fetch jobs being routed to postgres and 10% of all other jobs being routed to kafka and the rest to postgres
 */
export function getProducerMapping(stringMapping: string): CyclotronJobQueueRouting {
    const routing: CyclotronJobQueueRouting = {}
    const parts = stringMapping.split(',')

    const validQueues = ['*', ...HOG_FUNCTION_INVOCATION_JOB_QUEUES]

    for (const part of parts) {
        const [queue, target, percentageString] = part.split(':')

        if (!validQueues.includes(queue)) {
            throw new Error(`Invalid mapping: ${part} - queue ${queue} must be one of ${validQueues.join(', ')}`)
        }

        // change the type to the correct one once validated
        if (!CYCLOTRON_JOB_QUEUE_KINDS.includes(target as CyclotronJobQueueKind)) {
            throw new Error(
                `Invalid mapping: ${part} - target ${target} must be one of ${CYCLOTRON_JOB_QUEUE_KINDS.join(', ')}`
            )
        }

        let percentage = 1

        if (percentageString) {
            const parsedPercentage = parseFloat(percentageString)
            if (isNaN(parsedPercentage) || parsedPercentage < 0 || parsedPercentage > 1) {
                throw new Error(
                    `Invalid mapping: ${part} - percentage ${percentageString} must be a number between 0 and 1`
                )
            }
            percentage = parsedPercentage
        }

        if (routing[queue]) {
            throw new Error(`Duplicate mapping: ${part}`)
        }

        routing[queue] = {
            target: target as CyclotronJobQueueKind,
            percentage,
        }
    }

    if (!routing['*']) {
        throw new Error('No mapping for the default queue for example: *:postgres')
    }

    return routing
}
