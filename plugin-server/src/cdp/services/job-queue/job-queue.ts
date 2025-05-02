/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */

import { Counter, Gauge } from 'prom-client'

import { PluginsServerConfig } from '../../../types'
import { logger } from '../../../utils/logger'
import {
    CYCLOTRON_JOB_QUEUE_KINDS,
    CyclotronJobQueueKind,
    HOG_FUNCTION_INVOCATION_JOB_QUEUES,
    HogFunctionInvocation,
    HogFunctionInvocationJobQueue,
    HogFunctionInvocationResult,
} from '../../types'
import { HogFunctionManagerService } from '../hog-function-manager.service'
import { CyclotronJobQueueKafka } from './job-queue-kafka'
import { CyclotronJobQueuePostgres } from './job-queue-postgres'

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

export type CyclotronJobQueueRouting = {
    [key: string]: {
        target: CyclotronJobQueueKind
        percentage: number
    }
}

export class CyclotronJobQueue {
    private consumerMode: CyclotronJobQueueKind
    private producerMapping: CyclotronJobQueueRouting
    private jobQueuePostgres: CyclotronJobQueuePostgres
    private jobQueueKafka: CyclotronJobQueueKafka

    constructor(
        private config: PluginsServerConfig,
        private queue: HogFunctionInvocationJobQueue,
        private hogFunctionManager: HogFunctionManagerService,
        private _consumeBatch?: (invocations: HogFunctionInvocation[]) => Promise<any>
    ) {
        this.consumerMode = this.config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE
        this.producerMapping = getProducerMapping(this.config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING)

        this.jobQueueKafka = new CyclotronJobQueueKafka(
            this.config,
            this.queue,
            this.hogFunctionManager,
            (invocations) => this.consumeBatch(invocations, 'kafka')
        )
        this.jobQueuePostgres = new CyclotronJobQueuePostgres(
            this.config,
            this.queue,
            this.hogFunctionManager,
            (invocations) => this.consumeBatch(invocations, 'postgres')
        )

        logger.info('🔄', 'CyclotronJobQueue initialized', {
            consumerMode: this.consumerMode,
            producerMapping: this.producerMapping,
        })
    }

    private async consumeBatch(invocations: HogFunctionInvocation[], source: CyclotronJobQueueKind) {
        cyclotronBatchUtilizationGauge
            .labels({ queue: this.queue, source })
            .set(invocations.length / this.config.CDP_CYCLOTRON_BATCH_SIZE)

        await this._consumeBatch!(invocations)
        counterJobsProcessed.inc({ queue: this.queue, source }, invocations.length)
    }
    /**
     * Helper to only start the producer related code (e.g. when not a consumer)
     */
    public async startAsProducer() {
        // We only need to connect to the queue targets that are configured
        const targets = new Set<CyclotronJobQueueKind>(Object.values(this.producerMapping).map((x) => x.target))

        if (targets.has('postgres')) {
            await this.jobQueuePostgres.startAsProducer()
        }

        if (targets.has('kafka')) {
            await this.jobQueueKafka.startAsProducer()
        }
    }

    public async start() {
        if (!this.consumeBatch) {
            throw new Error('consumeBatch is required to start the job queue')
        }

        // The consumer always needs the producers as well
        await this.startAsProducer()

        if (this.consumerMode === 'postgres') {
            await this.jobQueuePostgres.startAsConsumer()
        } else {
            await this.jobQueueKafka.startAsConsumer()
        }
    }

    public async stop() {
        await Promise.all([this.jobQueuePostgres.stop(), this.jobQueueKafka.stop()])
    }

    public isHealthy() {
        if (this.consumerMode === 'postgres') {
            return this.jobQueuePostgres.isHealthy()
        } else {
            return this.jobQueueKafka.isHealthy()
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
            await this.jobQueuePostgres.queueInvocations(postgresInvocations)
        }
        if (kafkaInvocations.length > 0) {
            await this.jobQueueKafka.queueInvocations(kafkaInvocations)
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
            await this.jobQueuePostgres.queueInvocationResults(postgresInvocationsToUpdate)
        }

        if (postgresInvocationsToCreate.length > 0) {
            await this.jobQueuePostgres.queueInvocations(postgresInvocationsToCreate.map((x) => x.invocation))
        }

        if (kafkaInvocations.length > 0) {
            await this.jobQueueKafka.queueInvocationResults(kafkaInvocations)

            const jobsToRelease = kafkaInvocations
                .filter((x) => x.invocation.queueSource === 'postgres')
                .map((x) => x.invocation)

            if (jobsToRelease.length > 0) {
                await this.jobQueuePostgres.releaseInvocations(jobsToRelease)
            }
        }
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
