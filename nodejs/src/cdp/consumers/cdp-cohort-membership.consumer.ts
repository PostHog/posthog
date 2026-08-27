import { Message } from 'node-rdkafka'
import { z } from 'zod'

import { KAFKA_COHORT_MEMBERSHIP_CHANGED, KAFKA_COHORT_RECONCILE_MARKERS } from '~/common/config/kafka-topics'
import { getKafkaConfigFromEnv } from '~/common/kafka/config'
import { KafkaConsumerInterface, RdKafkaConsumerConfig, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresUse, TransactionClient } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { HealthCheckResult } from '../../types'
import type { CdpConfig } from '../config'
import {
    CohortMembershipSweeper,
    MembershipWatermarks,
    PRODUCER_VERSION_FORMAT,
} from '../services/cohort-membership/sweeper.service'
import { CdpConsumerBase, CdpConsumerBaseConfig, CdpConsumerBaseDeps } from './cdp-base.consumer'

export type CdpCohortMembershipConsumerConfig = CdpConsumerBaseConfig &
    Pick<
        CdpConfig,
        | 'COHORT_MEMBERSHIP_SWEEP_ENABLED'
        | 'COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS'
        | 'COHORT_MEMBERSHIP_SWEEP_BATCH_SIZE'
        | 'COHORT_MEMBERSHIP_SWEEP_CLAIM_TIMEOUT_MS'
        | 'COHORT_MEMBERSHIP_SWEEP_ABANDON_AFTER_DAYS'
    >

// Markers from runs that predate the sweeper are useless — the next reconcile heals anyway.
const startAtLatest = { ['auto.offset.reset' as keyof RdKafkaConsumerConfig]: 'latest' as never }

/**
 * The broker list the membership consumer resolves, mirroring the consumer's own config
 * resolution. Progress offsets are only comparable against watermarks from the same cluster, so
 * this keys every progress row: after a cluster move the old rows stop matching, and the gate
 * starts from no progress instead of comparing the old cluster's large offsets against the new
 * cluster's small watermarks.
 */
function membershipClusterId(): string {
    return String(getKafkaConfigFromEnv('CONSUMER')['metadata.broker.list'] ?? 'kafka:9092')
}

// `origin` is a loose string, not an enum: nothing branches on it, and rejecting a value the
// processor added later would throw the whole batch and crash-loop on redelivery.
const CohortMembershipChangeSchema = z.object({
    person_id: z.guid(),
    cohort_id: z.number(),
    team_id: z.number(),
    status: z.enum(['entered', 'left']),
    last_updated: z.string().optional(),
    origin: z.string().optional(),
    run_id: z.guid().optional(),
})

export type CohortMembershipChange = z.infer<typeof CohortMembershipChangeSchema>

/** How far the consumer has applied a partition, in the same units as a Kafka high watermark. */
type PartitionProgress = {
    partition: number
    nextOffset: number
}

/** What one reconcile run asserted in a single batch, folded into the run's running minimum. */
type SnapshotMark = {
    runId: string
    cohortId: number
    teamId: number
    minVersion: string
    rows: number
}

/**
 * A high watermark is the next offset to be produced, so consumer progress is recorded the same
 * way — as the next offset to consume. Comparing the two is then exact rather than off by one.
 */
function partitionProgressFromMessages(messages: Message[]): PartitionProgress[] {
    const maxOffsets = new Map<number, number>()

    for (const message of messages) {
        const current = maxOffsets.get(message.partition)
        if (current === undefined || message.offset > current) {
            maxOffsets.set(message.partition, message.offset)
        }
    }

    return Array.from(maxOffsets, ([partition, offset]) => ({ partition, nextOffset: offset + 1 }))
}

/**
 * The oldest version each reconcile run asserted in this batch. A sweep may only delete rows below
 * every version its run re-asserted, so the run's minimum is folded across batches in Postgres.
 *
 * Versions are compared as strings: the producer's format is fixed-width, so lexicographic order
 * is chronological order. A row carrying no version bounds nothing and is left out.
 *
 * The result is sorted by (run_id, cohort_id) because it feeds one multi-row upsert whose row
 * locks are held to commit: two pods writing the same runs in different orders would deadlock.
 */
function collectSnapshotMarks(changes: CohortMembershipChange[]): SnapshotMark[] {
    const marks = new Map<string, SnapshotMark>()

    for (const change of changes) {
        if (change.origin !== 'reconcile' || !change.run_id) {
            continue
        }

        if (!change.last_updated) {
            logger.warn('Reconcile membership change without a version, excluded from run marking', {
                run_id: change.run_id,
                cohort_id: change.cohort_id,
                team_id: change.team_id,
            })
            continue
        }

        const key = `${change.run_id}:${change.cohort_id}`
        const existing = marks.get(key)

        if (!existing) {
            marks.set(key, {
                runId: change.run_id,
                cohortId: change.cohort_id,
                teamId: change.team_id,
                minVersion: change.last_updated,
                rows: 1,
            })
            continue
        }

        existing.rows += 1
        if (change.last_updated < existing.minVersion) {
            existing.minVersion = change.last_updated
        }
    }

    return Array.from(marks.values()).sort((a, b) => a.runId.localeCompare(b.runId) || a.cohortId - b.cohortId)
}

export class CdpCohortMembershipConsumer extends CdpConsumerBase<CdpCohortMembershipConsumerConfig> {
    protected name = 'CdpCohortMembershipConsumer'
    private kafkaConsumer: KafkaConsumerInterface
    private markerKafkaConsumer: KafkaConsumerInterface | null = null
    private sweeper: CohortMembershipSweeper | null = null
    private membershipCluster = membershipClusterId()

    constructor(config: CdpCohortMembershipConsumerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-cohort-membership-consumer',
            topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
        })

        if (config.COHORT_MEMBERSHIP_SWEEP_ENABLED) {
            this.markerKafkaConsumer = createKafkaConsumer(
                { groupId: 'cdp-cohort-membership-sweeper', topic: KAFKA_COHORT_RECONCILE_MARKERS },
                startAtLatest
            )
            this.sweeper = new CohortMembershipSweeper(config, deps.postgres, {
                cluster: this.membershipCluster,
                captureMembershipWatermarks: () => this.captureMembershipWatermarks(),
                refreshConsumerProgress: () => this.refreshConsumerProgressFromCommittedOffsets(),
            })
        }
    }

    /**
     * A partition only gets a progress row when it delivers a batch, so one that holds retained
     * messages but receives no new traffic would block the gate forever. Committed offsets cover
     * every assigned partition, and the consumer commits only after a batch is applied, so they
     * are a safe lower bound on what reached Postgres. Each pod refreshes its own assignment;
     * together the fleet covers the topic.
     */
    private async refreshConsumerProgressFromCommittedOffsets(): Promise<void> {
        const committed = await this.kafkaConsumer.committedOffsets()

        const progress = committed
            .filter((entry) => entry.topic === KAFKA_COHORT_MEMBERSHIP_CHANGED && entry.offset >= 0)
            .map((entry) => ({ partition: entry.partition, nextOffset: entry.offset }))

        if (progress.length === 0) {
            return
        }

        await this.upsertConsumerProgress(PostgresUse.BEHAVIORAL_COHORTS_RW, progress)
    }

    /**
     * Read off the membership consumer's own client rather than the marker one: the two topics
     * share brokers today, but the processor keeps a separate marker producer so they could split.
     */
    private async captureMembershipWatermarks(): Promise<MembershipWatermarks> {
        // Asked of the broker rather than assumed. The processor's partition count governs the
        // marker set, not this topic's layout; hard-coding it here would silently stop covering
        // partitions above the assumed count, and the gate cannot wait on what it never captured.
        const metadata = await this.kafkaConsumer.getPartitionsForTopic(KAFKA_COHORT_MEMBERSHIP_CHANGED)

        if (metadata.length === 0) {
            throw new Error(`No partition metadata for ${KAFKA_COHORT_MEMBERSHIP_CHANGED}`)
        }

        // Partitions are never removed from a topic, so the progress rows the fleet has written
        // are a durable lower bound on the partition count. Metadata reporting fewer means the
        // broker returned a partial list (a refresh mid-leader-election, a reconfiguration);
        // capturing then would persist watermarks the gate treats as the full set, and the sweep
        // would fire while the missing partitions still hold unconsumed snapshot rows.
        const known = await this.deps.postgres.query<{ count: string }>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            'SELECT COUNT(*) AS count FROM cohort_membership_consumer_progress WHERE cluster = $1',
            [this.membershipCluster],
            'countCohortMembershipProgressPartitions'
        )

        const knownPartitions = Number(known.rows[0]?.count ?? 0)
        if (metadata.length < knownPartitions) {
            throw new Error(
                `Partial partition metadata for ${KAFKA_COHORT_MEMBERSHIP_CHANGED}: ` +
                    `broker reported ${metadata.length}, consumer progress covers ${knownPartitions}`
            )
        }

        const results = await Promise.all(
            metadata.map(async ({ id: partition }) => {
                const [, high] = await this.kafkaConsumer.queryWatermarkOffsets(
                    KAFKA_COHORT_MEMBERSHIP_CHANGED,
                    partition
                )
                return { partition, high }
            })
        )

        const watermarks: MembershipWatermarks = {}
        for (const { partition, high } of results) {
            watermarks[partition] = high
        }

        return watermarks
    }

    /**
     * Membership rows, the snapshot marks they carry, and the consumer's progress all land in one
     * transaction: progress must never claim offsets whose rows rolled back, or a sweep could
     * delete rows it believes were re-asserted.
     *
     * With the sweep flag off, none of the sweep bookkeeping is written and the upsert keeps the
     * pre-sweep single-statement shape against the pre-sweep schema. That keeps the migrations a
     * prerequisite of the flag flip only, not of every deploy: a pod reaching a database that has
     * not migrated yet must degrade to the old behavior, not crash-loop on a missing column.
     */
    private async persistCohortMembershipChanges(
        changes: CohortMembershipChange[],
        progress: PartitionProgress[] = []
    ): Promise<void> {
        if (changes.length === 0 && progress.length === 0) {
            return
        }

        try {
            // Deduplicate by (team_id, cohort_id, person_id), keeping the highest version so the
            // in-memory pick agrees with the SQL last-writer-wins guard; an absent version counts
            // as the oldest, and Kafka order breaks ties.
            const deduped = new Map<string, CohortMembershipChange>()
            for (const change of changes) {
                const key = `${change.team_id}:${change.cohort_id}:${change.person_id}`
                const existing = deduped.get(key)
                if (!existing || (change.last_updated ?? '') >= (existing.last_updated ?? '')) {
                    deduped.set(key, change)
                }
            }

            if (!this.config.COHORT_MEMBERSHIP_SWEEP_ENABLED) {
                if (deduped.size > 0) {
                    await this.upsertMembershipRowsWithoutVersion(Array.from(deduped.values()))
                }
                return
            }

            const marks = collectSnapshotMarks(changes)

            await this.deps.postgres.transaction(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                'cohortMembershipBatch',
                async (tx) => {
                    if (deduped.size > 0) {
                        await this.upsertMembershipRows(tx, Array.from(deduped.values()))
                    }
                    if (marks.length > 0) {
                        await this.upsertSnapshotMarks(tx, marks)
                    }
                    if (progress.length > 0) {
                        await this.upsertConsumerProgress(tx, progress)
                    }
                }
            )
        } catch (error) {
            logger.error('Failed to process batch cohort membership changes', {
                error,
                count: changes.length,
            })
            throw error
        }
    }

    /**
     * The version guard is what makes an at-least-once replay safe: offsets commit after the write,
     * so a crash replays a batch, and a stale reconcile row must not overwrite a newer live change
     * that was already applied. It is the same last-writer-wins rule ClickHouse applies to this
     * data. A row with no version counts as the oldest.
     */
    private async upsertMembershipRows(tx: TransactionClient, changes: CohortMembershipChange[]): Promise<void> {
        const values: any[] = []
        const placeholders: string[] = []
        let paramIndex = 1

        for (const change of changes) {
            placeholders.push(
                `($${paramIndex}, $${paramIndex + 1}, $${paramIndex + 2}, $${paramIndex + 3}, CURRENT_TIMESTAMP, $${
                    paramIndex + 4
                }::timestamp)`
            )
            values.push(
                change.team_id,
                change.cohort_id,
                change.person_id,
                change.status === 'entered',
                change.last_updated ?? null
            )
            paramIndex += 5
        }

        await this.deps.postgres.query(
            tx,
            `
                INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort, last_updated, version)
                VALUES ${placeholders.join(', ')}
                ON CONFLICT (team_id, cohort_id, person_id)
                DO UPDATE SET
                    in_cohort = EXCLUDED.in_cohort,
                    last_updated = CURRENT_TIMESTAMP,
                    version = EXCLUDED.version
                WHERE cohort_membership.version IS NULL OR EXCLUDED.version >= cohort_membership.version
            `,
            values,
            'batchUpsertCohortMembership'
        )
    }

    /** The flag-off shape: no version column, no transaction, valid against the pre-sweep schema. */
    private async upsertMembershipRowsWithoutVersion(changes: CohortMembershipChange[]): Promise<void> {
        const values: any[] = []
        const placeholders: string[] = []
        let paramIndex = 1

        for (const change of changes) {
            placeholders.push(
                `($${paramIndex}, $${paramIndex + 1}, $${paramIndex + 2}, $${paramIndex + 3}, CURRENT_TIMESTAMP)`
            )
            values.push(change.team_id, change.cohort_id, change.person_id, change.status === 'entered')
            paramIndex += 4
        }

        await this.deps.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort, last_updated)
                VALUES ${placeholders.join(', ')}
                ON CONFLICT (team_id, cohort_id, person_id)
                DO UPDATE SET
                    in_cohort = EXCLUDED.in_cohort,
                    last_updated = CURRENT_TIMESTAMP
            `,
            values,
            'batchUpsertCohortMembership'
        )
    }

    /**
     * Folds this batch's contribution into each run's ledger row. The row is created here when the
     * snapshot arrives before the run's completion markers, which is the normal ordering.
     */
    private async upsertSnapshotMarks(tx: TransactionClient, marks: SnapshotMark[]): Promise<void> {
        const values: any[] = []
        const placeholders: string[] = []
        let paramIndex = 1

        for (const mark of marks) {
            placeholders.push(
                `($${paramIndex}, $${paramIndex + 1}, $${paramIndex + 2}, $${paramIndex + 3}::timestamp, $${
                    paramIndex + 4
                })`
            )
            values.push(mark.runId, mark.cohortId, mark.teamId, mark.minVersion, mark.rows)
            paramIndex += 5
        }

        await this.deps.postgres.query(
            tx,
            `
                INSERT INTO cohort_membership_sweeps
                    (run_id, cohort_id, team_id, min_snapshot_version, snapshot_rows)
                VALUES ${placeholders.join(', ')}
                ON CONFLICT (run_id, cohort_id)
                DO UPDATE SET
                    min_snapshot_version = LEAST(
                        cohort_membership_sweeps.min_snapshot_version,
                        EXCLUDED.min_snapshot_version
                    ),
                    snapshot_rows = cohort_membership_sweeps.snapshot_rows + EXCLUDED.snapshot_rows,
                    updated_at = CURRENT_TIMESTAMP
            `,
            values,
            'markCohortMembershipSnapshot'
        )
    }

    /**
     * GREATEST keeps the gate monotone, so a rebalance that replays from an older committed offset
     * cannot walk a partition's progress backwards and unblock nothing that was already blocked.
     */
    private async upsertConsumerProgress(
        target: PostgresUse | TransactionClient,
        progress: PartitionProgress[]
    ): Promise<void> {
        const values: any[] = []
        const placeholders: string[] = []
        let paramIndex = 1

        for (const entry of progress) {
            placeholders.push(`($${paramIndex}, $${paramIndex + 1}, $${paramIndex + 2})`)
            values.push(this.membershipCluster, entry.partition, entry.nextOffset)
            paramIndex += 3
        }

        await this.deps.postgres.query(
            target,
            `
                INSERT INTO cohort_membership_consumer_progress (cluster, partition, next_offset)
                VALUES ${placeholders.join(', ')}
                ON CONFLICT (cluster, partition)
                DO UPDATE SET
                    next_offset = GREATEST(
                        cohort_membership_consumer_progress.next_offset,
                        EXCLUDED.next_offset
                    ),
                    updated_at = CURRENT_TIMESTAMP
            `,
            values,
            'upsertCohortMembershipProgress'
        )
    }

    private _parseAndValidateBatch(messages: Message[]): CohortMembershipChange[] {
        const cohortMembershipChanges: CohortMembershipChange[] = []

        // Process and validate all messages
        for (const message of messages) {
            try {
                const messageValue = message.value?.toString()
                if (!messageValue) {
                    throw new Error('Empty message received')
                }

                const parsedMessage = parseJSON(messageValue)

                // Validate using Zod schema
                const validationResult = CohortMembershipChangeSchema.safeParse(parsedMessage)

                if (!validationResult.success) {
                    logger.error('Invalid cohort membership change message', {
                        errors: validationResult.error.issues,
                        message: messageValue,
                    })
                    throw new Error(`Invalid cohort membership change message: ${validationResult.error.message}`)
                }

                const cohortMembershipChange = validationResult.data

                // A version is only usable in the producer's fixed-width format: it is compared
                // lexicographically and bound into `::timestamp` casts. Rejecting the message
                // would crash-loop the feed, so an off-format value degrades to "no version",
                // which last-writer-wins treats as the oldest.
                if (
                    cohortMembershipChange.last_updated &&
                    !PRODUCER_VERSION_FORMAT.test(cohortMembershipChange.last_updated)
                ) {
                    logger.warn('Dropping an off-format membership version', {
                        last_updated: cohortMembershipChange.last_updated,
                        team_id: cohortMembershipChange.team_id,
                        cohort_id: cohortMembershipChange.cohort_id,
                    })
                    cohortMembershipChange.last_updated = undefined
                }

                cohortMembershipChanges.push(cohortMembershipChange)
            } catch (error) {
                logger.error('Error processing cohort membership change message', {
                    error,
                    message: message.value?.toString(),
                })
                throw error
            }
        }

        return cohortMembershipChanges
    }

    private async handleBatch(messages: Message[]): Promise<void> {
        const cohortMembershipChanges = this._parseAndValidateBatch(messages)
        const progress = this.config.COHORT_MEMBERSHIP_SWEEP_ENABLED ? partitionProgressFromMessages(messages) : []
        await this.persistCohortMembershipChanges(cohortMembershipChanges, progress)
    }

    public override async start(): Promise<void> {
        await super.start()

        logger.info('🚀', `${this.name} starting...`)

        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return instrumentFn('cdpCohortMembershipConsumer.handleEachBatch', async () => {
                await this.handleBatch(messages)
            })
        })

        // Started after the membership consumer so its client is connected for watermark reads.
        if (this.markerKafkaConsumer && this.sweeper) {
            await this.markerKafkaConsumer.connect(async (messages) => {
                return instrumentFn('cdpCohortMembershipConsumer.handleMarkerBatch', async () => {
                    await this.handleMarkerBatch(messages)
                })
            })

            // The topic is not auto-created, and a consumer subscribed to a missing topic is a
            // green pod that marks nothing: every run would sit `collecting` until abandonment.
            // The flag being set is a claim that the environment has the topic, so hold it to that.
            const markerPartitions =
                await this.markerKafkaConsumer.getPartitionsForTopic(KAFKA_COHORT_RECONCILE_MARKERS)
            if (markerPartitions.length === 0) {
                throw new Error(
                    `COHORT_MEMBERSHIP_SWEEP_ENABLED is set but ${KAFKA_COHORT_RECONCILE_MARKERS} has no partitions`
                )
            }

            this.sweeper.start()
        }
    }

    /**
     * Never rethrows: this batch's offsets commit either way, and a throw would escape to the
     * consumer loop and take the membership consumer in the same process down with it. Parsing and
     * marker application each degrade per message instead.
     */
    private async handleMarkerBatch(messages: Message[]): Promise<void> {
        const sweeper = this.sweeper
        if (!sweeper) {
            return
        }

        try {
            await sweeper.applyMarkers(sweeper.parseMarkers(messages))
        } catch (error) {
            logger.error('Failed to process a reconcile marker batch', {
                error: String(error),
                count: messages.length,
            })
        }
    }

    public override async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.sweeper?.stop()
        // The marker path reads watermarks off the membership client, so that client disconnects
        // only after the marker consumer has fully drained.
        await this.markerKafkaConsumer?.disconnect()
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        const results = [this.kafkaConsumer.isHealthy(), this.markerKafkaConsumer?.isHealthy()].filter(
            (result): result is HealthCheckResult => result !== undefined
        )

        return results.find((result) => result.status !== 'ok') ?? results[0]
    }
}
