import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'
import { z } from 'zod'

import { KAFKA_COHORT_MEMBERSHIP_CHANGED, KAFKA_COHORT_RECONCILE_MARKERS } from '~/common/config/kafka-topics'
import { getKafkaConfigFromEnv } from '~/common/kafka/config'
import { KafkaConsumerInterface, START_AT_LATEST, createKafkaConsumer } from '~/common/kafka/consumer'
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
    VERSIONLESS,
} from '../services/cohort-membership/sweeper.service'
import { CdpConsumerBase, CdpConsumerBaseConfig, CdpConsumerBaseDeps } from './cdp-base.consumer'

export type CdpCohortMembershipConsumerConfig = CdpConsumerBaseConfig &
    Pick<
        CdpConfig,
        | 'COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED'
        | 'COHORT_MEMBERSHIP_SWEEP_ENABLED'
        | 'COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS'
        | 'COHORT_MEMBERSHIP_SWEEP_BATCH_SIZE'
        | 'COHORT_MEMBERSHIP_SWEEP_CLAIM_TIMEOUT_MS'
        | 'COHORT_MEMBERSHIP_SWEEP_ABANDON_AFTER_DAYS'
    >

/**
 * The broker list the membership consumer resolves, mirroring the consumer's own config
 * resolution. Progress offsets are only comparable against watermarks from the same feed, so
 * this keys every progress row together with the topic: after a cluster move or a topic change
 * the old rows stop matching, and the gate starts from no progress instead of comparing another
 * feed's large offsets against the current feed's small watermarks.
 */
function membershipClusterId(): string {
    return String(getKafkaConfigFromEnv('CONSUMER')['metadata.broker.list'] ?? 'kafka:9092')
}

const offFormatVersions = new Counter({
    name: 'cdp_cohort_membership_off_format_versions',
    help: 'Membership changes whose version stamp broke the producer contract and was degraded to versionless',
})

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
 * is chronological order.
 *
 * A reconcile change with no version still applies to its row while preserving the row's old
 * stamp (see upsertMembershipRows), so skipping it here would leave the run's minimum above that
 * stamp and the sweep would delete a person its own run just asserted. Folding the sentinel in
 * collapses the run's threshold instead: the sweep deletes nothing, and the next reconcile
 * retries with a clean run.
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
            logger.warn('Reconcile membership change without a version, collapsing the run threshold', {
                run_id: change.run_id,
                cohort_id: change.cohort_id,
                team_id: change.team_id,
            })
        }
        const version = change.last_updated ?? VERSIONLESS

        const key = `${change.run_id}:${change.cohort_id}`
        const existing = marks.get(key)

        if (!existing) {
            marks.set(key, {
                runId: change.run_id,
                cohortId: change.cohort_id,
                teamId: change.team_id,
                minVersion: version,
                rows: 1,
            })
            continue
        }

        existing.rows += 1
        if (version < existing.minVersion) {
            existing.minVersion = version
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

        if (config.COHORT_MEMBERSHIP_SWEEP_ENABLED && !config.COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED) {
            // The sweep deletes against the bookkeeping the version-writes flag produces, so a
            // pod sweeping while its own write path skips versions is always a misconfiguration.
            throw new Error(
                'COHORT_MEMBERSHIP_SWEEP_ENABLED requires COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED: ' +
                    'version writes turn on first and off last, sweeping turns on last and off first'
            )
        }

        if (config.COHORT_MEMBERSHIP_SWEEP_ENABLED) {
            // Markers from runs that predate the sweeper are useless, because the next reconcile
            // heals anyway, so a fresh sweeper group starts at the tip of the marker topic.
            this.markerKafkaConsumer = createKafkaConsumer(
                { groupId: 'cdp-cohort-membership-sweeper', topic: KAFKA_COHORT_RECONCILE_MARKERS },
                START_AT_LATEST
            )
            this.sweeper = new CohortMembershipSweeper(config, deps.postgres, {
                cluster: this.membershipCluster,
                topic: KAFKA_COHORT_MEMBERSHIP_CHANGED,
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
            'SELECT COUNT(*) AS count FROM cohort_membership_consumer_progress WHERE cluster = $1 AND topic = $2',
            [this.membershipCluster, KAFKA_COHORT_MEMBERSHIP_CHANGED],
            'countCohortMembershipProgressPartitions'
        )

        const knownPartitions = Number(known.rows[0]?.count ?? 0)
        // With no progress rows yet (first enable, or a cluster move re-keyed them) there is no
        // floor to validate the metadata against, and a truncated list would pass as the full
        // set. Refusing fails closed: the fleet writes a progress row from its first applied
        // batch, and a run cannot have a snapshot minimum before some batch was applied, so this
        // clears itself before any run is promotable.
        if (knownPartitions === 0) {
            throw new Error(
                `No recorded consumer progress for ${KAFKA_COHORT_MEMBERSHIP_CHANGED} on this cluster yet, ` +
                    'cannot validate partition metadata'
            )
        }
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
     * With the version-writes flag off, none of the sweep bookkeeping is written and the upsert
     * keeps the pre-sweep single-statement shape against the pre-sweep schema. That keeps the
     * migrations a prerequisite of the flag flip only, not of every deploy: a pod reaching a
     * database that has not migrated yet must degrade to the old behavior, not crash-loop on a
     * missing column.
     */
    private async persistCohortMembershipChanges(
        changes: CohortMembershipChange[],
        progress: PartitionProgress[] = []
    ): Promise<void> {
        if (changes.length === 0 && progress.length === 0) {
            return
        }

        try {
            // Deduplicate by (team_id, cohort_id, person_id). With version writes on, the highest
            // version wins so the in-memory pick agrees with the SQL last-writer-wins guard, with
            // Kafka order breaking ties; a versionless change applies unconditionally in SQL, so
            // it also has to win the in-batch pick when it arrives later in Kafka order. With
            // version writes off there is no SQL guard to agree with, so the last message in
            // Kafka order wins and the deploy stays a behavioral no-op until the flag flips.
            const versionAware = this.config.COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED
            const deduped = new Map<string, CohortMembershipChange>()
            for (const change of changes) {
                const key = `${change.team_id}:${change.cohort_id}:${change.person_id}`
                const existing = deduped.get(key)
                if (
                    !existing ||
                    !versionAware ||
                    !change.last_updated ||
                    change.last_updated >= (existing.last_updated ?? '')
                ) {
                    deduped.set(key, change)
                }
            }

            if (!this.config.COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED) {
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
     * data. A row stamped `-infinity` counts as the oldest, which is what the column default makes
     * every row written before this feature.
     *
     * An incoming change with no version cannot be ordered, but it is still a membership
     * transition: it applies unconditionally (the pre-version behavior) while GREATEST keeps the
     * row's existing stamp. Without both, an unordered change would lose to every stamped row and
     * be silently dropped, leaving the member stuck.
     */
    private async upsertMembershipRows(tx: TransactionClient, changes: CohortMembershipChange[]): Promise<void> {
        await this.deps.postgres.query(
            tx,
            `
                INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort, last_updated, version)
                SELECT unnest($1::bigint[]), unnest($2::bigint[]), unnest($3::uuid[]),
                       unnest($4::boolean[]), CURRENT_TIMESTAMP, unnest($5::timestamp[])
                ON CONFLICT (team_id, cohort_id, person_id)
                DO UPDATE SET
                    in_cohort = EXCLUDED.in_cohort,
                    last_updated = CURRENT_TIMESTAMP,
                    version = GREATEST(cohort_membership.version, EXCLUDED.version)
                WHERE EXCLUDED.version = '${VERSIONLESS}'
                   OR EXCLUDED.version >= cohort_membership.version
            `,
            [
                changes.map((change) => change.team_id),
                changes.map((change) => change.cohort_id),
                changes.map((change) => change.person_id),
                changes.map((change) => change.status === 'entered'),
                changes.map((change) => change.last_updated ?? VERSIONLESS),
            ],
            'batchUpsertCohortMembership'
        )
    }

    /**
     * The version-writes-off shape: no version column, no transaction, valid against the
     * pre-sweep schema.
     *
     * Once the schema is migrated, rows this path creates take the column default and are
     * therefore sweepable, and a re-asserted row keeps whatever stamp it already carried. The
     * rollout order is what keeps this path and a sweeping pod from ever coexisting in one fleet:
     * version writes turn on first and off last, sweeping turns on last and off first. The
     * constructor enforces the per-pod half of that contract.
     */
    private async upsertMembershipRowsWithoutVersion(changes: CohortMembershipChange[]): Promise<void> {
        await this.deps.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                INSERT INTO cohort_membership (team_id, cohort_id, person_id, in_cohort, last_updated)
                SELECT unnest($1::bigint[]), unnest($2::bigint[]), unnest($3::uuid[]),
                       unnest($4::boolean[]), CURRENT_TIMESTAMP
                ON CONFLICT (team_id, cohort_id, person_id)
                DO UPDATE SET
                    in_cohort = EXCLUDED.in_cohort,
                    last_updated = CURRENT_TIMESTAMP
            `,
            [
                changes.map((change) => change.team_id),
                changes.map((change) => change.cohort_id),
                changes.map((change) => change.person_id),
                changes.map((change) => change.status === 'entered'),
            ],
            'batchUpsertCohortMembershipWithoutVersion'
        )
    }

    /**
     * Folds this batch's contribution into each run's ledger row. The row is created here when the
     * snapshot arrives before the run's completion markers, which is the normal ordering.
     */
    private async upsertSnapshotMarks(tx: TransactionClient, marks: SnapshotMark[]): Promise<void> {
        await this.deps.postgres.query(
            tx,
            `
                INSERT INTO cohort_membership_sweeps
                    (run_id, cohort_id, team_id, min_snapshot_version, snapshot_rows)
                SELECT unnest($1::uuid[]), unnest($2::bigint[]), unnest($3::bigint[]),
                       unnest($4::timestamp[]), unnest($5::bigint[])
                ON CONFLICT (run_id, cohort_id)
                DO UPDATE SET
                    min_snapshot_version = LEAST(
                        cohort_membership_sweeps.min_snapshot_version,
                        EXCLUDED.min_snapshot_version
                    ),
                    snapshot_rows = cohort_membership_sweeps.snapshot_rows + EXCLUDED.snapshot_rows,
                    updated_at = CURRENT_TIMESTAMP
            `,
            [
                marks.map((mark) => mark.runId),
                marks.map((mark) => mark.cohortId),
                marks.map((mark) => mark.teamId),
                marks.map((mark) => mark.minVersion),
                marks.map((mark) => mark.rows),
            ],
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
        // Row locks are held to commit, and the batch path and the sweep loop hand partitions in
        // in different orders, so every writer has to take them in the same order. GREATEST makes
        // the result order-independent, so sorting here is safe.
        const sorted = [...progress].sort((a, b) => a.partition - b.partition)

        await this.deps.postgres.query(
            target,
            `
                INSERT INTO cohort_membership_consumer_progress (cluster, topic, partition, next_offset)
                SELECT $1, $2, unnest($3::int[]), unnest($4::bigint[])
                ON CONFLICT (cluster, topic, partition)
                DO UPDATE SET
                    next_offset = GREATEST(
                        cohort_membership_consumer_progress.next_offset,
                        EXCLUDED.next_offset
                    ),
                    updated_at = CURRENT_TIMESTAMP
            `,
            [
                this.membershipCluster,
                KAFKA_COHORT_MEMBERSHIP_CHANGED,
                sorted.map((entry) => entry.partition),
                sorted.map((entry) => entry.nextOffset),
            ],
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
                // would crash-loop the feed, so an off-format value degrades to "no version": the
                // membership transition still applies, but the row keeps its old stamp, so a
                // later run's sweep can delete it until a versioned write lands. A degraded
                // reconcile change additionally collapses its own run's threshold (see
                // collectSnapshotMarks).
                if (
                    cohortMembershipChange.last_updated &&
                    !PRODUCER_VERSION_FORMAT.test(cohortMembershipChange.last_updated)
                ) {
                    offFormatVersions.inc()
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
        const progress = this.config.COHORT_MEMBERSHIP_VERSION_WRITES_ENABLED
            ? partitionProgressFromMessages(messages)
            : []
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
            // A consumer subscribed to a missing topic is a green pod that marks nothing: every
            // run would sit `collecting` until abandonment. The flag being set is a claim that
            // this environment runs the US-scoped cohort pipeline that produces the topic, so
            // hold it to that. The fix for tripping this is to unset the flag, not to create the
            // topic: a marker topic with no processor behind it turns the loud failure back into
            // the silent one.
            //
            // The probe reads off the membership client, before the marker consumer connects:
            // connect() creates the topic when CONSUMER_AUTO_CREATE_TOPICS is on (the default),
            // which would make this check pass exactly where it has to fail. It assumes the two
            // topics share brokers, which is today's deployment; a future split fails here
            // loudly rather than passing silently.
            const markerPartitions = await this.kafkaConsumer.getPartitionsForTopic(KAFKA_COHORT_RECONCILE_MARKERS)
            if (markerPartitions.length === 0) {
                throw new Error(
                    `COHORT_MEMBERSHIP_SWEEP_ENABLED is set but ${KAFKA_COHORT_RECONCILE_MARKERS} has no partitions`
                )
            }

            await this.markerKafkaConsumer.connect(async (messages) => {
                return instrumentFn('cdpCohortMembershipConsumer.handleMarkerBatch', async () => {
                    await this.handleMarkerBatch(messages)
                })
            })

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
