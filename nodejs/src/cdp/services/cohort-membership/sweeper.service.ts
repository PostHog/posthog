import { Message } from 'node-rdkafka'
import { Counter, Gauge } from 'prom-client'
import { z } from 'zod'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { retryIfRetriable } from '~/common/utils/retries'
import { UUIDT } from '~/common/utils/utils'

/**
 * One completion marker per processor partition certifies a reconcile run. Must match the
 * processor's `cohort_partition_count` (`rust/cohort-stream-processor/src/config.rs`), which is 64
 * in production but env-overridable; on an environment running fewer partitions the bitmap never
 * completes and every sweep is a no-op, surfaced only by runs aging into abandonment.
 */
export const COHORT_PARTITION_COUNT = 64

/**
 * The producer's fixed-width version stamp, so lexicographic order is chronological order. Pinned
 * wherever a stamp is bound into a `::timestamp` cast: anything Postgres cannot parse would throw
 * out of the batch and take the consumer down with it.
 */
export const PRODUCER_VERSION_FORMAT = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}$/

/**
 * The stamp for a membership row the pipeline never versioned. Must stay equal to the column
 * default in `20260826000001_add_version_to_cohort_membership.sql`: every row written before that
 * migration reads as this value, and the sweep deletes below a threshold, so a sentinel that does
 * not sort below every producer stamp would leave stale rows behind. The delete pager also starts
 * its keyset cursor here, so a value that stopped matching the column default would make the
 * first page match nothing.
 */
export const VERSIONLESS = '-infinity'

/** All 64 bits set, read as a signed 64-bit integer. Same convention as the seeder's ledger. */
const ALL_MARKERS = '-1'

/** The marker topic's retention. Past this a run's markers cannot be redelivered, so a run still
 * unswept by then is unrecoverable and its ledger row is only hygiene. */
const MARKER_RETENTION_DAYS = 30

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
    last_updated: z.string().regex(PRODUCER_VERSION_FORMAT),
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
    membership_cluster: string | null
    membership_topic: string | null
    threshold: string | null
    claim_token: string | null
}

/**
 * The rule for which runs may be swept, shared by the tick scan and the claim UPDATE so the two
 * cannot drift: only the copy inside the claim actually protects the delete.
 *
 * A run with no snapshot minimum is never claimable. Marker stamps alone cannot bound the
 * snapshot: a fast partition finishes and stamps its marker while a slower one is still emitting
 * rows, so the earliest marker can sit above rows the run asserted. Sweeping there would delete
 * live members. Such a run waits for abandonment instead. This also excludes a run whose snapshot
 * was legitimately empty (a cohort edited so nobody matches): it can never prove a snapshot
 * minimum, so its stale rows outlive every reconcile until they are cleaned up out of band.
 */
function claimablePredicate(intervalParam: string): string {
    return `min_snapshot_version IS NOT NULL
                  AND (status = 'ready'
                       OR (status = 'sweeping' AND claimed_at < CURRENT_TIMESTAMP - ${intervalParam}::interval))`
}

const CLAIMABLE_PROJECTION = `run_id, cohort_id, team_id, membership_hwms,
                       membership_cluster, membership_topic,
                       LEAST(min_snapshot_version, min_marker_version) AS threshold, claim_token`

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
    help: 'Reconcile runs given up on, by the state they were stuck in',
    labelNames: ['reason'],
})

const sweepCycles = new Counter({
    name: 'cdp_cohort_membership_sweep_cycles',
    help: 'Sweep cycles run, by outcome. A cycle that only ever errors sweeps nothing, silently',
    labelNames: ['status'],
})

const sweepGateWaitSeconds = new Gauge({
    name: 'cdp_cohort_membership_sweep_gate_wait_seconds',
    help: 'Time since the oldest gate-blocked run completed its marker set',
})

/**
 * Deletes `cohort_membership` rows that a completed reconcile run did not re-assert.
 *
 * The consumer only ever upserts, so a person who stops matching an edited cohort keeps an
 * `in_cohort = true` row forever. A reconcile run emits one row per person holding a `cf_stage2`
 * register row for the cohort and then certifies itself with one marker per partition; persons
 * with no register row get nothing, and their versioned rows older than the run are what the
 * sweep deletes.
 */
export class CohortMembershipSweeper {
    private running = false
    private stopping = false
    private loopPromise: Promise<void> | null = null
    private sleepResolve: (() => void) | null = null

    constructor(
        private config: CohortMembershipSweepConfig,
        private postgres: PostgresRouter,
        /** All three describe the membership consumer's own client: the marker topic may live on another cluster. */
        private kafka: {
            /** Broker identity half of the progress-row key; offsets are only comparable within one cluster. */
            cluster: string
            /** Topic half of the progress-row key; the watermarks and the progress offsets both describe it. */
            topic: string
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
     * The bits are a union and the version stamp is a minimum, so a batch folds per run in memory
     * first: one statement per (run_id, cohort_id) instead of one per marker, and a full batch of
     * one run's markers is a single write. Redelivery changes nothing either way.
     *
     * This path runs inside the marker consumer's batch, whose offsets commit whether or not each
     * fold landed, so a failed fold is retried and then counted rather than rethrown: a rethrow
     * would take the membership consumer in the same process down with it. A lost fold leaves the
     * run short until it ages into abandonment, which `sweepsAbandoned` surfaces, and the next
     * reconcile heals the cohort.
     */
    public async applyMarkers(markers: ReconcileCompleteMarker[]): Promise<void> {
        type FoldedMarkers = {
            runId: string
            cohortId: number
            teamId: number
            bits: bigint
            minVersion: string
            partitions: number[]
        }
        const folded = new Map<string, FoldedMarkers>()

        for (const marker of markers) {
            const key = `${marker.run_id}:${marker.cohort_id}`
            const existing = folded.get(key)

            if (!existing) {
                folded.set(key, {
                    runId: marker.run_id,
                    cohortId: marker.cohort_id,
                    teamId: marker.team_id,
                    bits: BigInt(1) << BigInt(marker.partition),
                    minVersion: marker.last_updated,
                    partitions: [marker.partition],
                })
                continue
            }

            existing.bits |= BigInt(1) << BigInt(marker.partition)
            existing.partitions.push(marker.partition)
            if (marker.last_updated < existing.minVersion) {
                existing.minVersion = marker.last_updated
            }
        }

        for (const entry of folded.values()) {
            // Postgres bigint is signed, so the last partition's bit has to fold to the sign bit.
            const bits = BigInt.asIntN(64, entry.bits).toString()

            try {
                await retryIfRetriable(() =>
                    this.postgres.query(
                        PostgresUse.BEHAVIORAL_COHORTS_RW,
                        `
                            INSERT INTO cohort_membership_sweeps
                                (run_id, cohort_id, team_id, marker_bits, min_marker_version)
                            VALUES ($1, $2, $3, $4::bigint, $5::timestamp)
                            ON CONFLICT (run_id, cohort_id)
                            DO UPDATE SET
                                marker_bits = cohort_membership_sweeps.marker_bits | $4::bigint,
                                min_marker_version = LEAST(
                                    cohort_membership_sweeps.min_marker_version,
                                    EXCLUDED.min_marker_version
                                ),
                                updated_at = CURRENT_TIMESTAMP
                        `,
                        [entry.runId, entry.cohortId, entry.teamId, bits, entry.minVersion],
                        'applyCohortReconcileMarker'
                    )
                )
            } catch (error) {
                markersConsumed.inc({ outcome: 'apply_failed' }, entry.partitions.length)
                logger.error('Failed to apply reconcile markers', {
                    error: String(error),
                    run_id: entry.runId,
                    cohort_id: entry.cohortId,
                    partitions: entry.partitions,
                })
            }
        }
    }

    /**
     * Turns fully-marked runs claimable. This lives in the sweep loop rather than the marker batch
     * because capturing watermarks talks to Kafka and can fail transiently; the loop retries every
     * tick until it lands, while a throw inside the marker batch would kill the pod.
     */
    private async promoteMarkedRuns(): Promise<void> {
        const marked = await this.postgres.query<{ run_id: string; cohort_id: string; team_id: string }>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                SELECT run_id, cohort_id, team_id FROM cohort_membership_sweeps
                WHERE status = 'collecting' AND marker_bits = ${ALL_MARKERS}
                LIMIT ${MAX_CANDIDATES_PER_TICK}
            `,
            undefined,
            'findMarkedCohortMembershipSweeps'
        )

        if (marked.rows.length === 0) {
            return
        }

        // Every snapshot row of these runs was acked before its last marker was produced, so
        // watermarks read now bound each whole snapshot on the membership topic. Reading later
        // than the completion only raises the bar the gate waits for, never lowers it.
        const watermarks = await this.kafka.captureMembershipWatermarks()

        for (const run of marked.rows) {
            await this.postgres.query(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                `
                    UPDATE cohort_membership_sweeps
                    SET status = 'ready', membership_hwms = $1::jsonb,
                        membership_cluster = $4, membership_topic = $5,
                        ready_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE run_id = $2 AND cohort_id = $3
                      AND status = 'collecting' AND marker_bits = ${ALL_MARKERS}
                `,
                [JSON.stringify(watermarks), run.run_id, run.cohort_id, this.kafka.cluster, this.kafka.topic],
                'readyCohortMembershipSweep'
            )

            logger.info('Reconcile run is fully marked and ready to sweep', {
                run_id: run.run_id,
                cohort_id: run.cohort_id,
                team_id: run.team_id,
            })
        }
    }

    public async runOnce(): Promise<SweepCycleResult> {
        const result: SweepCycleResult = { swept: 0, rowsDeleted: 0, blocked: 0, abandoned: 0 }

        // Promotion talks to Kafka and its partial-metadata guard can fail permanently (a topic
        // recreated with fewer partitions). Letting the throw abort the cycle would also skip the
        // hygiene steps below, including the progress GC that eventually clears exactly that
        // cause, so a promotion failure is contained to its own outcome.
        try {
            await this.promoteMarkedRuns()
        } catch (error) {
            sweepCycles.inc({ status: 'promote_error' })
            logger.error('Failed to promote fully-marked reconcile runs', { error: String(error) })
        }

        await this.kafka.refreshConsumerProgress()
        const progress = await this.readConsumerProgress()

        for (const run of await this.claimableRuns()) {
            if (this.stopping) {
                break
            }

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

            const deleted = await this.sweep(claimed)
            if (deleted === null) {
                continue
            }

            result.rowsDeleted += deleted
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
     * delete only ever removes rows below a threshold that does not move. See claimablePredicate
     * for why a run with no snapshot minimum is excluded.
     */
    private async claimableRuns(): Promise<ClaimableRun[]> {
        const result = await this.postgres.query<ClaimableRun>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                SELECT ${CLAIMABLE_PROJECTION}
                FROM cohort_membership_sweeps
                WHERE ${claimablePredicate('$1')}
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
            'SELECT partition, next_offset FROM cohort_membership_consumer_progress WHERE cluster = $1 AND topic = $2',
            [this.kafka.cluster, this.kafka.topic],
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

        // An offset only means something against the feed it was read from. If the consumer's
        // brokers were repointed or the processor's output topic changed after this run captured
        // its watermarks, the two sides of the comparison describe different feeds and the gate
        // proves nothing. Refusing holds the run until it ages into abandonment, and the next
        // reconcile produces a run stamped with the current feed.
        if (run.membership_cluster !== this.kafka.cluster || run.membership_topic !== this.kafka.topic) {
            logger.warn('Refusing to sweep a run whose watermarks came from another feed', {
                run_id: run.run_id,
                cohort_id: run.cohort_id,
                captured_cluster: run.membership_cluster,
                captured_topic: run.membership_topic,
                current_cluster: this.kafka.cluster,
                current_topic: this.kafka.topic,
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
        const claimToken = new UUIDT().toString()

        const result = await this.postgres.query<ClaimableRun>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                UPDATE cohort_membership_sweeps
                SET status = 'sweeping', claimed_at = CURRENT_TIMESTAMP, claim_token = $4,
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = $1 AND cohort_id = $2
                  AND ${claimablePredicate('$3')}
                RETURNING ${CLAIMABLE_PROJECTION}
            `,
            [
                run.run_id,
                run.cohort_id,
                `${this.config.COHORT_MEMBERSHIP_SWEEP_CLAIM_TIMEOUT_MS} milliseconds`,
                claimToken,
            ],
            'claimCohortMembershipSweep'
        )

        return result.rows[0] ?? null
    }

    /** Returns the deleted row count, or null when the run was refused rather than swept. */
    private async sweep(run: ClaimableRun): Promise<number | null> {
        if (!run.threshold) {
            return await this.abandonThresholdless(run)
        }

        const { deleted, claimLost, interrupted } = await this.deleteStaleRowsInPages(run)
        rowsSwept.inc(deleted)
        if (claimLost) {
            // The new claim owner finishes the run and writes its terminal ledger row.
            return deleted
        }

        const finished = !interrupted && (await this.noRowsBelowThreshold(run))
        await this.finishSweep(run, deleted, finished)
        return deleted
    }

    /**
     * Unreachable while claim() requires a snapshot minimum; kept so a future claim change cannot
     * silently delete below no bound. Abandoning gives the row a terminal state instead of
     * leaving it wedged in 'sweeping'.
     */
    private async abandonThresholdless(run: ClaimableRun): Promise<null> {
        logger.error('Refusing to sweep a run with no threshold', {
            run_id: run.run_id,
            cohort_id: run.cohort_id,
        })
        await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                UPDATE cohort_membership_sweeps
                SET status = 'abandoned', claimed_at = NULL, claim_token = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE run_id = $1 AND cohort_id = $2 AND status = 'sweeping' AND claim_token = $3
            `,
            [run.run_id, run.cohort_id, run.claim_token],
            'abandonThresholdlessCohortMembershipSweep'
        )
        sweepsAbandoned.inc({ reason: 'no_threshold' })
        return null
    }

    private async deleteStaleRowsInPages(
        run: ClaimableRun
    ): Promise<{ deleted: number; claimLost: boolean; interrupted: boolean }> {
        let deleted = 0
        let lastBatch = 0
        // Keyset cursor over the (team_id, cohort_id, version) index order. Deleted index entries
        // stay visible to a scan until VACUUM, so restarting each page from the range start would
        // walk past every previously-deleted entry again.
        //
        // The cursor starts at the same sentinel the column defaults to, and `>` on the row
        // constructor still advances through those rows by id. `to_char` returns NULL for an
        // infinite timestamp, so the RETURNING clause restores the sentinel text: without it the
        // cursor would take a NULL and the next page would match nothing.
        let cursorVersion: string = VERSIONLESS
        let cursorId = '0'

        do {
            // The predicate is repeated in the DELETE on purpose: under READ COMMITTED the DELETE
            // re-checks it against the newest row version, so a row a concurrent upsert just
            // refreshed past the threshold is left alone instead of deleted anyway. A refreshed
            // row also leaves the cursor range entirely, so skipping past it loses nothing.
            //
            // The threshold bound into `version < $3` was parsed to millisecond precision on the
            // way out of Postgres, so it can sit up to 999 microseconds below the stored minimum.
            // Truncation only ever lowers it, which makes the sweep under-delete, never
            // over-delete; the next reconcile deletes the sliver it leaves behind.
            const result = await this.postgres.query<{ version: string; id: string }>(
                PostgresUse.BEHAVIORAL_COHORTS_RW,
                `
                    WITH candidates AS (
                        SELECT id FROM cohort_membership
                        WHERE team_id = $1 AND cohort_id = $2
                          AND version < $3::timestamp
                          AND (version, id) > ($5::timestamp, $6::bigint)
                        ORDER BY version, id
                        LIMIT $4
                        FOR UPDATE SKIP LOCKED
                    )
                    DELETE FROM cohort_membership m
                    USING candidates c
                    WHERE m.id = c.id AND m.version < $3::timestamp
                    RETURNING COALESCE(
                        to_char(m.version, 'YYYY-MM-DD HH24:MI:SS.US'), '${VERSIONLESS}'
                    ) AS version, m.id
                `,
                [
                    run.team_id,
                    run.cohort_id,
                    run.threshold,
                    this.config.COHORT_MEMBERSHIP_SWEEP_BATCH_SIZE,
                    cursorVersion,
                    cursorId,
                ],
                'sweepCohortMembership'
            )

            lastBatch = result.rowCount ?? 0
            deleted += lastBatch

            for (const row of result.rows) {
                if (
                    row.version > cursorVersion ||
                    (row.version === cursorVersion && BigInt(row.id) > BigInt(cursorId))
                ) {
                    cursorVersion = row.version
                    cursorId = row.id
                }
            }

            // Without this the claim goes stale mid-run and every other pod reclaims the same
            // cohort, so N pods page over the same rows. Zero rows updated means the claim is no
            // longer ours (reclaimed after a stall, or abandoned); the new owner finishes the run.
            if (lastBatch > 0) {
                const heartbeat = await this.postgres.query(
                    PostgresUse.BEHAVIORAL_COHORTS_RW,
                    `UPDATE cohort_membership_sweeps SET claimed_at = CURRENT_TIMESTAMP
                     WHERE run_id = $1 AND cohort_id = $2 AND status = 'sweeping' AND claim_token = $3`,
                    [run.run_id, run.cohort_id, run.claim_token],
                    'heartbeatCohortMembershipSweep'
                )

                if ((heartbeat.rowCount ?? 0) === 0) {
                    logger.warn('Lost the sweep claim mid-run, yielding to the new owner', {
                        run_id: run.run_id,
                        cohort_id: run.cohort_id,
                        rows: deleted,
                    })
                    return { deleted, claimLost: true, interrupted: false }
                }
            }
        } while (lastBatch > 0 && !this.stopping)

        // Interrupted by shutdown; the run goes back to 'ready' and resumes on the next claim.
        return { deleted, claimLost: false, interrupted: this.stopping && lastBatch > 0 }
    }

    /**
     * A zero-delete iteration means either nothing is left or SKIP LOCKED skipped everything.
     * Only the first is finished; calling the second `swept` would retire the run with stale rows
     * still in place, and nothing revisits a swept run.
     */
    private async noRowsBelowThreshold(run: ClaimableRun): Promise<boolean> {
        const remaining = await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `SELECT 1 FROM cohort_membership
             WHERE team_id = $1 AND cohort_id = $2 AND version < $3::timestamp
             LIMIT 1`,
            [run.team_id, run.cohort_id, run.threshold],
            'checkCohortMembershipSweepComplete'
        )
        return remaining.rows.length === 0
    }

    /**
     * The claim token fences stragglers: a pod whose claim timed out and was reclaimed no longer
     * matches, so it cannot overwrite the new owner's state nor resurrect a run that was
     * abandoned in between. swept_rows accumulates across partial passes.
     */
    private async finishSweep(run: ClaimableRun, deleted: number, finished: boolean): Promise<void> {
        await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                UPDATE cohort_membership_sweeps
                SET status = $1, swept_rows = COALESCE(swept_rows, 0) + $2,
                    claimed_at = NULL, claim_token = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = $3 AND cohort_id = $4 AND status = 'sweeping' AND claim_token = $5
            `,
            [finished ? 'swept' : 'ready', deleted, run.run_id, run.cohort_id, run.claim_token],
            'finishCohortMembershipSweep'
        )

        logger.info('Swept stale cohort membership rows', {
            run_id: run.run_id,
            cohort_id: run.cohort_id,
            team_id: run.team_id,
            rows: deleted,
            finished,
        })
    }

    /**
     * Two distinct give-up paths, kept apart because only one is routine. A reconcile superseded
     * by a cohort edit emits no marker, so its `collecting` row can never complete; that is
     * expected traffic, and the short timeout retires it. Every proven run gets the
     * marker-retention horizon instead, because abandoning it sooner would discard a run that
     * would have swept: a `ready` run is only waiting on consumer lag, a `sweeping` run only ever
     * fails transiently, and a `collecting` run holding every marker is only waiting on watermark
     * capture, which the sweep loop retries each tick.
     *
     * These filters and the GC below scan without an index; the ledger is bounded by the GC to a
     * month of reconcile runs, so a sequential scan stays trivial.
     */
    private async abandonStuckRuns(): Promise<number> {
        const unmarked = await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                UPDATE cohort_membership_sweeps
                SET status = 'abandoned', updated_at = CURRENT_TIMESTAMP
                WHERE status = 'collecting'
                  AND marker_bits <> ${ALL_MARKERS}
                  AND updated_at < CURRENT_TIMESTAMP - $1::interval
            `,
            [`${this.config.COHORT_MEMBERSHIP_SWEEP_ABANDON_AFTER_DAYS} days`],
            'abandonUnmarkedCohortMembershipSweeps'
        )

        const unmarkedCount = unmarked.rowCount ?? 0
        if (unmarkedCount > 0) {
            sweepsAbandoned.inc({ reason: 'markers_incomplete' }, unmarkedCount)
            logger.warn('Abandoned reconcile runs that never completed their marker set', { count: unmarkedCount })
        }

        const unswept = await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                UPDATE cohort_membership_sweeps
                SET status = 'abandoned', claim_token = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE (status IN ('ready', 'sweeping')
                       OR (status = 'collecting' AND marker_bits = ${ALL_MARKERS}))
                  AND created_at < CURRENT_TIMESTAMP - INTERVAL '${MARKER_RETENTION_DAYS} days'
            `,
            undefined,
            'abandonUnsweptCohortMembershipSweeps'
        )

        const unsweptCount = unswept.rowCount ?? 0
        if (unsweptCount > 0) {
            sweepsAbandoned.inc({ reason: 'never_swept' }, unsweptCount)
            logger.warn('Abandoned fully-marked reconcile runs whose sweep never completed', {
                count: unsweptCount,
            })
        }

        return unmarkedCount + unsweptCount
    }

    /** Matches the marker topic's retention, past which a run's markers cannot be redelivered. */
    private async collectGarbage(): Promise<void> {
        await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                DELETE FROM cohort_membership_sweeps
                WHERE status IN ('swept', 'abandoned')
                  AND updated_at < CURRENT_TIMESTAMP - INTERVAL '${MARKER_RETENTION_DAYS} days'
            `,
            undefined,
            'gcCohortMembershipSweeps'
        )

        // Progress rows keyed to a feed the consumer left, by cluster move or topic change, stop
        // updating and would otherwise sit forever.
        await this.postgres.query(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                DELETE FROM cohort_membership_consumer_progress
                WHERE updated_at < CURRENT_TIMESTAMP - INTERVAL '${MARKER_RETENTION_DAYS} days'
            `,
            undefined,
            'gcCohortMembershipProgress'
        )
    }

    private async recordGateWait(): Promise<void> {
        const result = await this.postgres.query<{ wait_seconds: string | null }>(
            PostgresUse.BEHAVIORAL_COHORTS_RW,
            `
                SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MIN(ready_at)))::text AS wait_seconds
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
        this.stopping = false
        this.loopPromise = this.sweepLoop()
        logger.info('CohortMembershipSweeper started', {
            intervalMs: this.config.COHORT_MEMBERSHIP_SWEEP_INTERVAL_MS,
        })
    }

    public async stop(): Promise<void> {
        // `stopping` breaks the paging loops inside a running cycle; without it, shutdown waits
        // for up to MAX_RUNS_PER_TICK full cohort sweeps to page to completion.
        this.stopping = true
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
