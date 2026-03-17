/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */
import { DateTime } from 'luxon'
import { Counter, Gauge } from 'prom-client'

import { HealthCheckResultError } from '../../../types'
import { logger } from '../../../utils/logger'
import { CdpConfig } from '../../config'
import {
    CYCLOTRON_INVOCATION_JOB_QUEUES,
    CYCLOTRON_JOB_QUEUE_SOURCES,
    CyclotronJobInvocation,
    CyclotronJobInvocationResult,
    CyclotronJobQueueKind,
    CyclotronJobQueueSource,
} from '../../types'
import { CyclotronJobQueueKafka } from './job-queue-kafka'
import { CyclotronJobQueuePostgres } from './job-queue-postgres'
import { CyclotronJobQueuePostgresV2 } from './job-queue-postgres-v2'
import { sanitizeInvocationForPersistence } from './shared'

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

export const JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS = 10 * 1000 // Any scheduled jobs need to be scheduled this much in the future to be considered for postgres
const PERCENTAGE_TOLERANCE = 0.001

export type CyclotronJobQueueRoutingEntry = {
    target: CyclotronJobQueueSource
    percentage: number
}

export type CyclotronJobQueueRouting = {
    [key: string]: CyclotronJobQueueRoutingEntry[]
}

export type CyclotronJobQueueTeamRouting = {
    [teamId: string]: CyclotronJobQueueRouting
}

export class CyclotronJobQueue {
    private queue?: CyclotronJobQueueKind
    private consumerMode?: CyclotronJobQueueSource
    private _consumeBatch?: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    private producerMapping: CyclotronJobQueueRouting
    private producerTeamMapping: CyclotronJobQueueTeamRouting
    private producerForceScheduledToPostgres: boolean
    private jobQueuePostgres: CyclotronJobQueuePostgres
    private jobQueuePostgresV2: CyclotronJobQueuePostgresV2 | null = null
    private jobQueueKafka: CyclotronJobQueueKafka

    constructor(
        private consumerBatchSize: number,
        private kafkaClientRack: string | undefined,
        private config: CdpConfig
    ) {
        this.producerMapping = getProducerMapping(this.config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING)
        this.producerTeamMapping = getProducerTeamMapping(this.config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_TEAM_MAPPING)
        this.producerForceScheduledToPostgres = this.config.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_FORCE_SCHEDULED_TO_POSTGRES
        this.jobQueueKafka = new CyclotronJobQueueKafka(this.kafkaClientRack, this.config)
        this.jobQueuePostgres = new CyclotronJobQueuePostgres(this.consumerBatchSize, this.config)

        if (this.config.CYCLOTRON_NODE_DATABASE_URL) {
            this.jobQueuePostgresV2 = new CyclotronJobQueuePostgresV2(this.consumerBatchSize, this.config)
        }

        logger.info('🔄', 'CyclotronJobQueue initialized', {
            producerMapping: this.producerMapping,
            producerTeamMapping: this.producerTeamMapping,
            v2Enabled: !!this.jobQueuePostgresV2,
        })
    }

    private async consumeBatch(
        invocations: CyclotronJobInvocation[],
        source: CyclotronJobQueueSource
    ): Promise<{ backgroundTask: Promise<any> }> {
        cyclotronBatchUtilizationGauge
            .labels({ queue: this.queue!, source })
            .set(invocations.length / this.consumerBatchSize)

        const result = await this._consumeBatch!(invocations)
        counterJobsProcessed.inc({ queue: this.queue!, source }, invocations.length)

        return result
    }
    /**
     * Helper to only start the producer related code (e.g. when not a consumer)
     */
    public async startAsProducer() {
        // We only need to connect to the queue targets that are configured

        const allEntries: CyclotronJobQueueRoutingEntry[] = []

        for (const teamId in this.producerTeamMapping) {
            for (const queue in this.producerTeamMapping[teamId]) {
                allEntries.push(...this.producerTeamMapping[teamId][queue])
            }
        }

        for (const queue in this.producerMapping) {
            allEntries.push(...this.producerMapping[queue])
        }

        const targets = new Set<CyclotronJobQueueSource>(allEntries.map((x) => x.target))

        if (targets.has('postgres') || this.producerForceScheduledToPostgres) {
            await this.jobQueuePostgres.startAsProducer()
        }

        if (targets.has('postgres-v2')) {
            await this.jobQueuePostgresV2?.startAsProducer()
        }

        if (targets.has('kafka')) {
            await this.jobQueueKafka.startAsProducer()
        }
    }

    public async start(
        queue: CyclotronJobQueueKind,
        consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>,
        consumerMode?: CyclotronJobQueueSource
    ) {
        this.queue = queue
        this._consumeBatch = consumeBatch
        this.consumerMode = consumerMode ?? this.config.CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE

        // The consumer always needs the producers as well
        await this.startAsProducer()

        if (this.consumerMode === 'postgres') {
            await this.jobQueuePostgres.startAsConsumer(queue, (invocations) =>
                this.consumeBatch(invocations, 'postgres')
            )
        } else if (this.consumerMode === 'postgres-v2') {
            if (!this.jobQueuePostgresV2) {
                throw new Error('Cyclotron V2 consumer mode requires CYCLOTRON_NODE_DATABASE_URL to be set')
            }
            await this.jobQueuePostgresV2.startAsConsumer(queue, (invocations) =>
                this.consumeBatch(invocations, 'postgres-v2')
            )
        } else if (this.consumerMode === 'kafka') {
            await this.jobQueueKafka.startAsConsumer(queue, (invocations) => this.consumeBatch(invocations, 'kafka'))
        }
    }

    public async stop() {
        // Important - first shut down the consumers so we aren't processing anything
        await Promise.all([
            this.jobQueuePostgres.stopConsumer(),
            this.jobQueuePostgresV2?.stopConsumer(),
            this.jobQueueKafka.stopConsumer(),
        ])

        // Only then do we shut down the producers
        await Promise.all([
            this.jobQueuePostgres.stopProducer(),
            this.jobQueuePostgresV2?.stopProducer(),
            this.jobQueueKafka.stopProducer(),
        ])
    }

    public isHealthy() {
        if (!this.consumerMode) {
            return new HealthCheckResultError('Consumer not started', {})
        } else if (this.consumerMode === 'postgres') {
            return this.jobQueuePostgres.isHealthy()
        } else if (this.consumerMode === 'postgres-v2') {
            return this.jobQueuePostgresV2?.isHealthy() ?? new HealthCheckResultError('V2 not enabled', {})
        } else if (this.consumerMode === 'kafka') {
            return this.jobQueueKafka.isHealthy()
        }

        return new HealthCheckResultError('Invalid consumer mode', {})
    }

    private getTarget(invocation: CyclotronJobInvocation): CyclotronJobQueueSource {
        const teamId = invocation.teamId
        const mapping = this.producerTeamMapping[teamId] ?? this.producerMapping
        const entries = mapping[invocation.queue] ?? mapping['*']

        let target: CyclotronJobQueueSource
        if (entries.length === 1) {
            target = entries[0].target
        } else {
            const roll = Math.random()
            let cumulative = 0
            target = entries[entries.length - 1].target
            for (const entry of entries) {
                cumulative += entry.percentage
                if (roll < cumulative) {
                    target = entry.target
                    break
                }
            }
        }

        if (
            target === 'kafka' &&
            this.producerForceScheduledToPostgres &&
            invocation.queueScheduledAt &&
            invocation.queueScheduledAt > DateTime.now().plus({ milliseconds: JOB_SCHEDULED_AT_FUTURE_THRESHOLD_MS }) &&
            invocation.queue !== 'hogoverflow' // overflow is always sent to kafka
        ) {
            // Kafka doesn't support delays so if enabled we should force scheduled jobs to postgres
            return 'postgres'
        }

        return target
    }

    public async queueInvocations(invocations: CyclotronJobInvocation[]) {
        const sanitized = invocations.map(sanitizeInvocationForPersistence)
        const postgresInvocations: CyclotronJobInvocation[] = []
        const postgresV2Invocations: CyclotronJobInvocation[] = []
        const kafkaInvocations: CyclotronJobInvocation[] = []

        for (const invocation of sanitized) {
            const target = this.getTarget(invocation)

            if (target === 'postgres') {
                postgresInvocations.push(invocation)
            } else if (target === 'postgres-v2') {
                postgresV2Invocations.push(invocation)
            } else {
                kafkaInvocations.push(invocation)
            }
        }

        await Promise.all([
            this.jobQueuePostgres.queueInvocations(postgresInvocations),
            this.jobQueuePostgresV2?.queueInvocations(postgresV2Invocations),
            this.jobQueueKafka.queueInvocations(kafkaInvocations),
        ])
    }

    public async dequeueInvocations(invocations: CyclotronJobInvocation[]) {
        // NOTE: This is only relevant to postgres backed jobs as kafka jobs can just be dropped
        const pgJobsToDequeue = invocations.filter((x) => x.queueSource === 'postgres')
        if (pgJobsToDequeue.length > 0) {
            await this.jobQueuePostgres.dequeueInvocations(pgJobsToDequeue)
        }

        const v2JobsToDequeue = invocations.filter((x) => x.queueSource === 'postgres-v2')
        if (v2JobsToDequeue.length > 0) {
            await this.jobQueuePostgresV2?.dequeueInvocations(v2JobsToDequeue)
        }
    }

    public async cancelInvocations(invocations: CyclotronJobInvocation[]) {
        // NOTE: This is only relevant to postgres backed jobs as kafka jobs can just be dropped
        const pgJobsToCancel = invocations.filter((x) => x.queueSource === 'postgres')
        if (pgJobsToCancel.length > 0) {
            await this.jobQueuePostgres.cancelInvocations(pgJobsToCancel)
        }

        const v2JobsToCancel = invocations.filter((x) => x.queueSource === 'postgres-v2')
        if (v2JobsToCancel.length > 0) {
            await this.jobQueuePostgresV2?.cancelInvocations(v2JobsToCancel)
        }
    }

    public async queueInvocationResults(invocationResults: CyclotronJobInvocationResult[]) {
        // TODO: Routing based on queue name is slightly tricky here as postgres jobs need to be acked no matter what...
        // We need to know if the job came from postgres and if so we need to ack, regardless of the target...

        const sanitizedResults = invocationResults.map((result) => ({
            ...result,
            invocation: sanitizeInvocationForPersistence(result.invocation),
        }))

        const postgresInvocationsToCreate: CyclotronJobInvocationResult[] = []
        const postgresInvocationsToUpdate: CyclotronJobInvocationResult[] = []
        const postgresV2InvocationsToUpdate: CyclotronJobInvocationResult[] = []
        const postgresV2InvocationsToCreate: CyclotronJobInvocationResult[] = []
        const kafkaInvocations: CyclotronJobInvocationResult[] = []

        for (const invocationResult of sanitizedResults) {
            const target = this.getTarget(invocationResult.invocation)

            if (target === 'postgres') {
                if (invocationResult.invocation.queueSource === 'postgres') {
                    postgresInvocationsToUpdate.push(invocationResult)
                } else {
                    postgresInvocationsToCreate.push(invocationResult)
                }
            } else if (target === 'postgres-v2') {
                if (invocationResult.invocation.queueSource === 'postgres-v2') {
                    postgresV2InvocationsToUpdate.push(invocationResult)
                } else {
                    postgresV2InvocationsToCreate.push(invocationResult)
                }
            } else {
                kafkaInvocations.push(invocationResult)
            }
        }

        logger.debug('🔄', 'Queueing invocation results', {
            kafka: kafkaInvocations.map(
                (x) => `${x.invocation.id} (queue:${x.invocation.queue},source:${x.invocation.queueSource})`
            ),
            postgres_update: postgresInvocationsToUpdate.map(
                (x) => `${x.invocation.id} (queue:${x.invocation.queue},source:${x.invocation.queueSource})`
            ),
            postgres_create: postgresInvocationsToCreate.map(
                (x) => `${x.invocation.id} (queue:${x.invocation.queue},source:${x.invocation.queueSource})`
            ),
            postgres_v2_update: postgresV2InvocationsToUpdate.map(
                (x) => `${x.invocation.id} (queue:${x.invocation.queue},source:${x.invocation.queueSource})`
            ),
            postgres_v2_create: postgresV2InvocationsToCreate.map(
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

        if (postgresV2InvocationsToUpdate.length > 0 && this.jobQueuePostgresV2) {
            promises.push(this.jobQueuePostgresV2.queueInvocationResults(postgresV2InvocationsToUpdate))
        }

        if (postgresV2InvocationsToCreate.length > 0 && this.jobQueuePostgresV2) {
            promises.push(
                this.jobQueuePostgresV2.queueInvocations(postgresV2InvocationsToCreate.map((x) => x.invocation))
            )
        }

        if (kafkaInvocations.length > 0) {
            promises.push(this.jobQueueKafka.queueInvocationResults(kafkaInvocations))

            const jobsToRelease = kafkaInvocations
                .filter((x) => x.invocation.queueSource === 'postgres')
                .map((x) => x.invocation)

            if (jobsToRelease.length > 0) {
                promises.push(this.jobQueuePostgres.releaseInvocations(jobsToRelease))
            }

            const v2JobsToRelease = kafkaInvocations
                .filter((x) => x.invocation.queueSource === 'postgres-v2')
                .map((x) => x.invocation)

            if (v2JobsToRelease.length > 0 && this.jobQueuePostgresV2) {
                promises.push(this.jobQueuePostgresV2.releaseInvocations(v2JobsToRelease))
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

    const validQueues = ['*', ...CYCLOTRON_INVOCATION_JOB_QUEUES]

    for (const part of parts) {
        const [queue, target, percentageString] = part.split(':')

        if (!validQueues.includes(queue)) {
            throw new Error(`Invalid mapping: ${part} - queue ${queue} must be one of ${validQueues.join(', ')}`)
        }

        // change the type to the correct one once validated
        if (!CYCLOTRON_JOB_QUEUE_SOURCES.includes(target as CyclotronJobQueueSource)) {
            throw new Error(
                `Invalid mapping: ${part} - target ${target} must be one of ${CYCLOTRON_JOB_QUEUE_SOURCES.join(', ')}`
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

        if (!routing[queue]) {
            routing[queue] = []
        }

        routing[queue].push({
            target: target as CyclotronJobQueueSource,
            percentage,
        })
    }

    if (!routing['*']) {
        throw new Error('No mapping for the default queue for example: *:postgres')
    }

    // Validate that percentages sum to 1 for multi-target queues
    for (const [queue, entries] of Object.entries(routing)) {
        if (entries.length > 1) {
            const sum = entries.reduce((acc, e) => acc + e.percentage, 0)
            if (Math.abs(sum - 1) > PERCENTAGE_TOLERANCE) {
                throw new Error(`Invalid mapping for queue ${queue}: percentages must sum to 1 (got ${sum})`)
            }
        }
    }

    return routing
}

/**
 * Same as getProducerMapping but with a team prefix.
 * Entries for the same team are grouped together before parsing.
 *
 * Format: `TEAM:QUEUE:TARGET[:PERCENTAGE],...`
 *
 * For queue-specific overrides with percentages < 1, the remainder is automatically
 * filled from the team's `*` default.
 *
 * Example: `79155:*:kafka,79155:hog:postgres-v2:0.001` results in team 79155 routing
 * 0.1% of hog jobs to postgres-v2 and 99.9% to kafka (remainder filled from team's `*`).
 */
export function getProducerTeamMapping(stringMapping: string): CyclotronJobQueueTeamRouting {
    if (!stringMapping) {
        return {}
    }

    // Group parts by team ID
    const teamParts: Record<string, string[]> = {}
    for (const part of stringMapping.split(',')) {
        const [team, ...rest] = part.split(':')
        if (!team || rest.length < 2) {
            throw new Error(`Invalid team mapping: ${part} - expected format TEAM:QUEUE:TARGET[:PERCENTAGE]`)
        }
        if (!teamParts[team]) {
            teamParts[team] = []
        }
        teamParts[team].push(rest.join(':'))
    }

    const routing: CyclotronJobQueueTeamRouting = {}

    for (const [team, groupedParts] of Object.entries(teamParts)) {
        const teamRouting = getProducerMapping(groupedParts.join(','))

        // Fill remainder for queues where percentages don't sum to 1,
        // using the team's `*` default to fill the gap
        for (const [queue, entries] of Object.entries(teamRouting)) {
            if (queue === '*') {
                continue
            }
            const sum = entries.reduce((acc, e) => acc + e.percentage, 0)
            if (sum < 1 - PERCENTAGE_TOLERANCE) {
                const fallbackEntries = teamRouting['*']
                const remainder = 1 - sum
                const fallbackSum = fallbackEntries.reduce((acc, e) => acc + e.percentage, 0)
                for (const fallback of fallbackEntries) {
                    entries.push({
                        target: fallback.target,
                        percentage: (fallback.percentage / fallbackSum) * remainder,
                    })
                }
            }
        }

        routing[team] = teamRouting
    }

    return routing
}
