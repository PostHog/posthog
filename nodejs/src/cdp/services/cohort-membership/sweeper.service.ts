import { Message } from 'node-rdkafka'
import { Counter, Gauge } from 'prom-client'
import { z } from 'zod'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

/**
 * One completion marker per processor partition certifies a reconcile run. Kept in step with
 * `COHORT_PARTITION_COUNT` in `rust/cohort-core/src/partitioner.rs`, which is compile-time stable
 * by design — the marker topic's partition count is load-bearing for the same reason.
 */
export const COHORT_PARTITION_COUNT = 64

/** All 64 bits set, read as a signed 64-bit integer. Same convention as the seeder's ledger. */
const ALL_MARKERS = '-1'

/** A tick sweeps at most this many runs; the rest wait for the next one. */
const MAX_RUNS_PER_TICK = 10

/**
 * Candidates read per tick. Larger than the sweep cap because most candidates are usually waiting
 * on the gate, and a run cannot be told apart from a blocked one until it is read — a page the size
 * of the sweep cap would let a handful of blocked runs starve everything behind them.
 */
const MAX_CANDIDATES_PER_TICK = 200

const ReconcileCompleteMarkerSchema = z.object({
    type: z.literal('reconcile_complete'),
    team_id: z.number(),
    cohort_id: z.number(),
    partition: z
        .number()
        .int()
        .min(0)
        .max(COHORT_PARTITION_COUNT - 1),
    run_id: z.guid(),
    // The producer's fixed-width stamp. Pinned here because it is bound straight into a
    // `::timestamp` cast: anything Postgres cannot parse would throw out of the marker batch and
    // take the membership consumer down with it.
    last_updated: z.string().regex(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}$/),
})

export type ReconcileCompleteMarker = z.infer<typeof ReconcileCompleteMarkerSchema>

/** Membership-topic high watermarks at marker completeness, keyed by partition. */
export type MembershipWatermarks = Record<number, number>

export type CohortMembershipSweepConfig = {
    COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS: number
    COHORT_MEMBERSHIP_SWEEP_BATCH_SIZE: number
    COHORT_MEMBERSHIP_SWEEP_CLAIM_TIMEOUT_MS: number
    COHORT_MEMBERSHIP_SWEEP_ABANDON_AFTER_DAYS: number
}

export type SweepCycleResult = {
    swept: number
    rowsDeleted: number
    blocked: number
    abandoned: number
}

type ClaimableRun = {
    run_id: string
    cohort_id: string
    team_id: string
    membership_hwms: MembershipWatermarks | null
    threshold: string | null
}

const markersConsumed = new Counter({
    name: 'cdp_cohort_membership_markers_consumed',
    help: 'Reconcile completion markers read off the marker topic, by parse outcome',
    labelNames: ['outcome'],
})

const sweepsExecuted = new Counter({
    name: 'cdp_cohort_membership_sweeps_executed',
    help: 'Reconcile runs whose stale rows were swept',
})

const rowsSwept = new Counter({
    name: 'cdp_cohort_membership_rows_swept',
    help: 'Stale cohort_membership rows deleted by a sweep',
})

const sweepsGateBlocked = new Counter({
    name: 'cdp_cohort_membership_sweeps_gate_blocked',
    help: 'Sweep attempts held back because the membership consumer had not passed the snapshot',
})

const sweepsAbandoned = new Counter({
    name: 'cdp_cohort_membership_sweeps_abandoned',
    help: 'Reconcile runs given up on because their marker set never completed',
})

const sweepCycles = new Counter({
    name: 'cdp_cohort_membership_sweep_cycles',
    help: 'Sweep cycles run, by outcome. A cycle that only ever errors sweeps nothing, silently',
    labelNames: ['status'],
})

const sweepGateWaitSeconds = new Gauge({
    name: 'cdp_cohort_membership_sweep_gate_wait_seconds',
    help: 'Time since the oldest fully-marked run was last written to, while it waits on the gate',
})

/**
 * Deletes `cohort_membership` rows that a completed reconcile run did not re-assert.
 *
 * The consumer only ever upserts, so a person who stops matching an edited cohort keeps an
 * `in_cohort = true` row forever. A reconcile run replays the cohort's full current membership and
 * then certifies itself with one marker per partition; everything the run stamped older than
 * itself is by definition no longer a member.
 */
export class CohortMembershipSweeper {
    private running = false
    private loopPromise: Promise<void> | null = null
    private sleepResolve: (() => void) | null = null

    constructor(
        private config: CohortMembershipSweepConfig,
        private postgres: PostgresRouter,
        /** Both read the membership consumer's own client: the two topics may live on different clusters. */
        private kafka: {
            captureMembershipWatermarks: () => Promise<MembershipWatermarks>
            refreshConsumerProgress: () => Promise<void>
        }
    ) {}

    /**
     * One bad message must not wedge the sweep pipeline, so parsing skips and counts rather than
     * failing the batch the way the membership consumer does.
     */
    public parseMarkers(messages: Message[]): ReconcileCompleteMarker[] {
        const markers: ReconcileCompleteMarker[] = []

        for (const message of messages) {
            try {
                const value = message.value?.toString()
                if (!value) {
                    markersConsumed.inc({ outcome: 'skipped' })
                    continue
                }

                const parsed = ReconcileCompleteMarkerSchema.safeParse(parseJSON(value))
                if (!parsed.success) {
                    markersConsumed.inc({ outcome: 'skipped' })
                    logger.warn('Skipping unusable reconcile marker', {
                        errors: parsed.error.issues,
                    })
                    continue
                }

                markersConsumed.inc({ outcome: 'parsed' })
                markers.push(parsed.data)
            } catch (error) {
                markersConsumed.inc({ outcome: 'skipped' })
                logger.warn('Skipping unparseable reconcile marker', { error })
            }
        }

        return markers
    }

    /**
     * Folding a marker in is a bit union, so redelivery changes nothing. The run turns claimable
     * only on the transition to a complete set, and only once.
     */
    public async applyMarkers(markers: ReconcileCompleteMarker[]): Promise<void> {
        for (const marker of markers) {
            const result = await this.postgres.query<{ complete: boolean; status: string }>(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                `
                    INSERT INTO cohort_membership_sweeps
                        (run_id, cohort_id, team_id, marker_bits, min_marker_version)
                    VALUES ($1, $2, $3, (1::bigint << $4), $5::timestamp)
                    ON CONFLICT (run_id, cohort_id)
                    DO UPDATE SET
                        marker_bits = cohort_membership_sweeps.marker_bits | (1::bigint << $4),
                        min_marker_version = LEAST(
                            cohort_membership_sweeps.min_marker_version,
                            EXCLUDED.min_marker_version
                        ),
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING marker_bits = ${ALL_MARKERS} AS complete, status
                `,
                [marker.run_id, marker.cohort_id, marker.team_id, marker.partition, marker.last_updated],
                'applyCohortReconcileMarker'
            )

            const { complete, status } = result.rows[0]
            if (!complete || status !== 'collecting') {
                continue
            }

            // Every snapshot row of this run was acked before its marker was produced, so the
            // watermarks read now bound the whole snapshot on the membership topic.
            const watermarks = await this.kafka.captureMembershipWatermarks()

            await this.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                `
                    UPDATE cohort_membership_sweeps
                    SET status = 'ready', membership_hwms = $1::jsonb, updated_at = CURRENT_TIMESTAMP
                    WHERE run_id = $2 AND cohort_id = $3
                      AND status = 'collecting' AND marker_bits = ${ALL_MARKERS}
                `,
                [JSON.stringify(watermarks), marker.run_id, marker.cohort_id],
                'readyCohortMembershipSweep'
            )

            logger.info('Reconcile run is fully marked and ready to sweep', {
                run_id: marker.run_id,
                cohort_id: marker.cohort_id,
                team_id: marker.team_id,
            })
        }
    }

    public async runOnce(): Promise<SweepCycleResult> {
        const result: SweepCycleResult = { swept: 0, rowsDeleted: 0, blocked: 0, abandoned: 0 }

        await this.kafka.refreshConsumerProgress()
        const progress = await this.readConsumerProgress()

        for (const run of await this.claimableRuns()) {
            if (!this.gateSatisfied(run, progress)) {
                result.blocked += 1
                sweepsGateBlocked.inc()
                continue
            }

            if (result.swept >= MAX_RUNS_PER_TICK) {
                break
            }

            const claimed = await this.claim(run)
            if (!claimed) {
                continue
            }

            result.rowsDeleted += await this.sweep(claimed)
            result.swept += 1
            sweepsExecuted.inc()
        }

        result.abandoned = await this.abandonStuckRuns()
        await this.collectGarbage()
        await this.recordGateWait()

        sweepCycles.inc({ status: 'ok' })
        return result
    }

    /**
     * Runs that hold every marker, plus runs whose claiming pod died. Re-sweeping is harmless: the
     * delete only ever removes rows below a threshold that does not move.
     *
     * A run with no snapshot minimum is never claimable. Marker stamps alone cannot bound the
     * snapshot: a fast partition finishes and stamps its marker while a slower one is still
     * emitting rows, so the earliest marker can sit above rows the run asserted. Sweeping there
     * would delete live members — and every unversioned row with them. Such a run waits for
     * abandonment instead; the next reconcile heals the cohort.
     */
    private async claimableRuns(): Promise<ClaimableRun[]> {
        const result = await this.postgres.query<ClaimableRun>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                SELECT run_id, cohort_id, team_id, membership_hwms,
                       LEAST(min_snapshot_version, min_marker_version) AS threshold
                FROM cohort_membership_sweeps
                WHERE min_snapshot_version IS NOT NULL
                  AND (status = 'ready'
                       OR (status = 'sweeping' AND claimed_at < CURRENT_TIMESTAMP - $1::interval))
                ORDER BY created_at
                LIMIT ${MAX_CANDIDATES_PER_TICK}
            `,
            [`${this.config.COHORT_MEMBERSHIP_SWEEP_CLAIM_TIMEOUT_MS} milliseconds`],
            'findClaimableCohortMembershipSweeps'
        )

        return result.rows
    }

    private async readConsumerProgress(): Promise<Map<number, number>> {
        const result = await this.postgres.query<{ partition: number; next_offset: string }>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            'SELECT partition, next_offset FROM cohort_membership_consumer_progress',
            undefined,
            'readCohortMembershipProgress'
        )

        return new Map(result.rows.map((row) => [row.partition, Number(row.next_offset)]))
    }

    /**
     * Markers are a tiny topic; the membership topic carries the multi-million-row snapshot they
     * certify. Sweeping on markers alone would delete rows whose re-asserting messages are still
     * queued, blanking a cohort for flag evaluation until the consumer catches up.
     */
    private gateSatisfied(run: ClaimableRun, progress: Map<number, number>): boolean {
        const watermarks = Object.entries(run.membership_hwms ?? {})

        // No watermarks means the capture never happened or came back empty. An empty map would
        // otherwise satisfy every partition vacuously, which is the one way this gate can pass
        // without proving anything.
        if (watermarks.length === 0) {
            logger.warn('Refusing to sweep a run with no captured watermarks', {
                run_id: run.run_id,
                cohort_id: run.cohort_id,
            })
            return false
        }

        const blocked: number[] = []

        for (const [partition, highWatermark] of watermarks) {
            // Nothing was ever produced to this partition, so there is nothing to wait for.
            if (highWatermark <= 0) {
                continue
            }

            const applied = progress.get(Number(partition))
            if (applied === undefined || applied < highWatermark) {
                blocked.push(Number(partition))
            }
        }

        if (blocked.length > 0) {
            logger.info('Holding a cohort membership sweep until the consumer passes the snapshot', {
                run_id: run.run_id,
                cohort_id: run.cohort_id,
                blocked_partitions: blocked,
            })
            return false
        }

        return true
    }

    private async claim(run: ClaimableRun): Promise<ClaimableRun | null> {
        const result = await this.postgres.query<ClaimableRun>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                UPDATE cohort_membership_sweeps
                SET status = 'sweeping', claimed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = $1 AND cohort_id = $2
                  AND min_snapshot_version IS NOT NULL
                  AND (status = 'ready'
                       OR (status = 'sweeping' AND claimed_at < CURRENT_TIMESTAMP - $3::interval))
                RETURNING run_id, cohort_id, team_id, membership_hwms,
                          LEAST(min_snapshot_version, min_marker_version) AS threshold
            `,
            [run.run_id, run.cohort_id, `${this.config.COHORT_MEMBERSHIP_SWEEP_CLAIM_TIMEOUT_MS} milliseconds`],
            'claimCohortMembershipSweep'
        )

        return result.rows[0] ?? null
    }

    private async sweep(run: ClaimableRun): Promise<number> {
        if (!run.threshold) {
            logger.error('Refusing to sweep a run with no threshold', {
                run_id: run.run_id,
                cohort_id: run.cohort_id,
            })
            return 0
        }

        let deleted = 0
        let lastBatch = 0

        do {
            // The predicate is repeated in the DELETE on purpose: under READ COMMITTED the DELETE
            // re-checks it against the newest row version, so a row a concurrent upsert just
            // refreshed past the threshold is left alone instead of deleted anyway.
            const result = await this.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                `
                    WITH candidates AS (
                        SELECT id FROM cohort_membership
                        WHERE team_id = $1 AND cohort_id = $2
                          AND (version IS NULL OR version < $3::timestamp)
                        LIMIT $4
                        FOR UPDATE SKIP LOCKED
                    )
                    DELETE FROM cohort_membership m
                    USING candidates c
                    WHERE m.id = c.id AND (m.version IS NULL OR m.version < $3::timestamp)
                `,
                [run.team_id, run.cohort_id, run.threshold, this.config.COHORT_MEMBERSHIP_SWEEP_BATCH_SIZE],
                'sweepCohortMembership'
            )

            lastBatch = result.rowCount ?? 0
            deleted += lastBatch

            // Without this the claim goes stale mid-run and every other pod reclaims the same
            // cohort, so N pods page over the same rows.
            if (lastBatch > 0) {
                await this.postgres.query(
                    PostgresUse.BEHAVIORAL_COHORTS_RW,
                    `UPDATE cohort_membership_sweeps SET claimed_at = CURRENT_TIMESTAMP
                     WHERE run_id = $1 AND cohort_id = $2 AND status = 'sweeping'`,
                    [run.run_id, run.cohort_id],
                    'heartbeatCohortMembershipSweep'
                )
            }
        } while (lastBatch > 0)

        // A zero-delete iteration means either nothing is left or SKIP LOCKED skipped everything.
        // Only the first is finished; calling the second `swept` would retire the run with stale
        // rows still in place, and nothing revisits a swept run.
        const remaining = await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `SELECT 1 FROM cohort_membership
             WHERE team_id = $1 AND cohort_id = $2 AND (version IS NULL OR version < $3::timestamp)
             LIMIT 1`,
            [run.team_id, run.cohort_id, run.threshold],
            'checkCohortMembershipSweepComplete'
        )
        const finished = remaining.rows.length === 0

        // Guarded on 'sweeping' so a straggler cannot overwrite the pod that reclaimed the run, nor
        // resurrect one that was abandoned in between.
        await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                UPDATE cohort_membership_sweeps
                SET status = $1, swept_rows = $2, claimed_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = $3 AND cohort_id = $4 AND status = 'sweeping'
            `,
            [finished ? 'swept' : 'ready', deleted, run.run_id, run.cohort_id],
            'finishCohortMembershipSweep'
        )

        rowsSwept.inc(deleted)
        logger.info('Swept stale cohort membership rows', {
            run_id: run.run_id,
            cohort_id: run.cohort_id,
            team_id: run.team_id,
            rows: deleted,
            finished,
        })

        return deleted
    }

    /**
     * A reconcile superseded by a cohort edit emits no marker, so its set can never complete. The
     * row is only table hygiene at that point.
     */
    private async abandonStuckRuns(): Promise<number> {
        const result = await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                UPDATE cohort_membership_sweeps
                SET status = 'abandoned', updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('collecting', 'ready')
                  AND updated_at < CURRENT_TIMESTAMP - $1::interval
            `,
            [`${this.config.COHORT_MEMBERSHIP_SWEEP_ABANDON_AFTER_DAYS} days`],
            'abandonCohortMembershipSweeps'
        )

        const abandoned = result.rowCount ?? 0
        if (abandoned > 0) {
            sweepsAbandoned.inc(abandoned)
            logger.warn('Abandoned reconcile runs that never completed their marker set', { count: abandoned })
        }

        return abandoned
    }

    /** Matches the marker topic's retention, past which a run's markers cannot be redelivered. */
    private async collectGarbage(): Promise<void> {
        await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                DELETE FROM cohort_membership_sweeps
                WHERE status IN ('swept', 'abandoned')
                  AND updated_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
            `,
            undefined,
            'gcCohortMembershipSweeps'
        )
    }

    private async recordGateWait(): Promise<void> {
        const result = await this.postgres.query<{ wait_seconds: string | null }>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MIN(updated_at)))::text AS wait_seconds
                FROM cohort_membership_sweeps WHERE status = 'ready'
            `,
            undefined,
            'measureCohortMembershipGateWait'
        )

        sweepGateWaitSeconds.set(Number(result.rows[0]?.wait_seconds ?? 0))
    }

    public start(): void {
        if (this.running) {
            return
        }

        this.running = true
        this.loopPromise = this.sweepLoop()
        logger.info('CohortMembershipSweeper started', {
            intervalMs: this.config.COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS,
        })
    }

    public async stop(): Promise<void> {
        this.running = false
        this.sleepResolve?.()
        await this.loopPromise
        this.loopPromise = null
    }

    private async sweepLoop(): Promise<void> {
        while (this.running) {
            try {
                await this.runOnce()
            } catch (error) {
                sweepCycles.inc({ status: 'error' })
                logger.error('CohortMembershipSweeper cycle failed', { error: String(error) })
            }

            if (this.running) {
                let timer: NodeJS.Timeout | undefined
                await new Promise<void>((resolve) => {
                    this.sleepResolve = resolve
                    timer = setTimeout(resolve, this.config.COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS)
                })
                // stop() resolves the sleep early, which leaves the timer armed and the process held open.
                clearTimeout(timer)
                this.sleepResolve = null
            }
        }
    }
}
