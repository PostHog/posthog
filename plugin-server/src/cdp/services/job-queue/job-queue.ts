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

export type CyclotronJobQueueTeamRouting = {
    [teamId: string]: CyclotronJobQueueRouting
}

export class CyclotronJobQueue {
    private consumerMode: CyclotronJobQueueKind
    private producerMapping: CyclotronJobQueueRouting
    private producerTeamMapping: CyclotronJobQueueTeamRouting
    private producerForceScheduledToPostgres: boolean
    private jobQueuePostgres: CyclotronJobQueuePostgres
    private jobQueueKafka: CyclotronJobQueueKafka

    constructor(
        private config: PluginsServerConfig,
        private queue: HogFunctionInvocationJobQueue,
        private hogFunctionManager: HogFunctionManagerService,
        private _consumeBatch?: (invocations: HogFunctionInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ) {
        this.consumerMode = this.config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE
        this.producerMapping = getProducerMapping(this.config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING)
        this.producerTeamMapping = getProducerTeamMapping(this.config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING)
        this.producerForceScheduledToPostgres = this.config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_FORCE_SCHEDULED_TO_POSTGRES

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
            producerTeamMapping: this.producerTeamMapping,
        })
    }

    private async consumeBatch(
        invocations: HogFunctionInvocation[],
        source: CyclotronJobQueueKind
    ): Promise<{ backgroundTask: Promise<any> }> {
        cyclotronBatchUtilizationGauge
            .labels({ queue: this.queue, source })
            .set(invocations.length / this.config.CDP_CYCLOTRON_BATCH_SIZE)

        const result = await this._consumeBatch!(invocations)
        counterJobsProcessed.inc({ queue: this.queue, source }, invocations.length)

        return result
    }
    /**
     * Helper to only start the producer related code (e.g. when not a consumer)
     */
    public async startAsProducer() {
        // We only need to connect to the queue targets that are configured

        const allTargets: {
            target: CyclotronJobQueueKind
            percentage: number
        }[] = []

        for (const teamId in this.producerTeamMapping) {
            allTargets.push(...Object.values(this.producerTeamMapping[teamId]))
        }

        for (const queue in this.producerMapping) {
            allTargets.push({
                target: this.producerMapping[queue].target,
                percentage: this.producerMapping[queue].percentage,
            })
        }

        const targets = new Set<CyclotronJobQueueKind>(allTargets.map((x) => x.target))

        // If any target is a non-100% then we need both producers ready
        const anySplitRouting = allTargets.some((x) => x.percentage < 1)

        if (anySplitRouting || targets.has('postgres') || this.producerForceScheduledToPostgres) {
            await this.jobQueuePostgres.startAsProducer()
        }

        if (anySplitRouting || targets.has('kafka')) {
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

    private getTarget(invocation: HogFunctionInvocation): CyclotronJobQueueKind {
        if (this.producerForceScheduledToPostgres && invocation.queueScheduledAt) {
            // Kafka doesn't support delays so if enabled we should force scheduled jobs to postgres
            return 'postgres'
        }

        const teamId = invocation.teamId
        const mapping = this.producerTeamMapping[teamId] ?? this.producerMapping
        const producerConfig = mapping[invocation.queue] ?? mapping['*']

        let target = producerConfig.target

        if (producerConfig.percentage < 1) {
            const otherTarget = target === 'postgres' ? 'kafka' : 'postgres'
            target = Math.random() < producerConfig.percentage ? target : otherTarget
        }

        return target
    }

    public async queueInvocations(invocations: HogFunctionInvocation[]) {
        const postgresInvocations: HogFunctionInvocation[] = []
        const kafkaInvocations: HogFunctionInvocation[] = []

        for (const invocation of invocations) {
            const target = this.getTarget(invocation)

            if (target === 'postgres') {
                postgresInvocations.push(invocation)
            } else {
                kafkaInvocations.push(invocation)
            }
        }

        await Promise.all([
            this.jobQueuePostgres.queueInvocations(postgresInvocations),
            this.jobQueueKafka.queueInvocations(kafkaInvocations),
        ])
    }

    public async queueInvocationResults(invocationResults: HogFunctionInvocationResult[]) {
        // TODO: Routing based on queue name is slightly tricky here as postgres jobs need to be acked no matter what...
        // We need to know if the job came from postgres and if so we need to ack, regardless of the target...

        const postgresInvocationsToCreate: HogFunctionInvocationResult[] = []
        const postgresInvocationsToUpdate: HogFunctionInvocationResult[] = []
        const kafkaInvocations: HogFunctionInvocationResult[] = []

        for (const invocationResult of invocationResults) {
            const target = this.getTarget(invocationResult.invocation)

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

        const promises: Promise<any>[] = []

        if (postgresInvocationsToUpdate.length > 0) {
            promises.push(this.jobQueuePostgres.queueInvocationResults(postgresInvocationsToUpdate))
        }

        if (postgresInvocationsToCreate.length > 0) {
            promises.push(this.jobQueuePostgres.queueInvocations(postgresInvocationsToCreate.map((x) => x.invocation)))
        }

        if (kafkaInvocations.length > 0) {
            promises.push(this.jobQueueKafka.queueInvocationResults(kafkaInvocations))

            const jobsToRelease = kafkaInvocations
                .filter((x) => x.invocation.queueSource === 'postgres')
                .map((x) => x.invocation)

            if (jobsToRelease.length > 0) {
                promises.push(this.jobQueuePostgres.releaseInvocations(jobsToRelease))
            }
        }

        await Promise.all(promises)
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
            if (isNaN(parsedPercentage) || parsedPercentage <= 0 || parsedPercentage > 1) {
                throw new Error(`Invalid mapping: ${part} - percentage ${percentageString} must be 0 < x <= 1`)
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

/**
 * Same as getProducerMapping but with a team check too.
 * So for example `1:*:kafka,2:*:postgres` would result in team 1 using kafka and team 2 using postgres
 */
export function getProducerTeamMapping(stringMapping: string): CyclotronJobQueueTeamRouting {
    if (!stringMapping) {
        return {}
    }

    const routing: CyclotronJobQueueTeamRouting = {}
    const parts = stringMapping.split(',')

    for (const part of parts) {
        const [team, ...rest] = part.split(':')
        routing[team] = getProducerMapping(rest.join(':'))
    }

    return routing
}
