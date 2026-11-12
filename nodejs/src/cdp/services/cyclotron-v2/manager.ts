import { Pool, QueryResult } from 'pg'
import { Counter, Histogram } from 'prom-client'
import { v7 as uuidv7 } from 'uuid'

import { isTransientPgError } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { sleep } from '~/common/utils/utils'

import { BatchResolverResumeOutcome, resumeParkedBatchResolver } from '../hogflows/batch-resolver-resume'
import { StepResume, StepResumeOutcome, processStepResumes } from '../hogflows/step-resume.service'
import { QUEUE_DEPTH_SQL, cappedQueueDepthSql } from './due-rows-sql'
import { createCyclotronPool } from './pg-pool'
import {
    CYCLOTRON_COUNTER_MAX,
    CyclotronV2CancelJobsOptions,
    CyclotronV2CancelJobsResult,
    CyclotronV2InFlightCounts,
    CyclotronV2JobInit,
    CyclotronV2JobInitSchema,
    CyclotronV2ManagerConfig,
    CyclotronV2RescheduleParkedOptions,
    CyclotronV2RescheduleParkedResult,
} from './types'

/**
 * Block size used to compute the fair-dequeue sort key for email queue jobs:
 *
 *     dequeue_seq = counter * EMAIL_DEQUEUE_BLOCK_SIZE + team_id
 *
 * 2^24 (16,777,216) — supports team_ids up to ~16M (PostHog is well under
 * that). Keeps headroom for ~5 × 10^11 jobs per team before the BIGINT
 * sort key overflows, which is centuries at any realistic email volume.
 *
 * Only used for queue_name='email'. Other queues leave dequeue_seq NULL.
 */
export const EMAIL_DEQUEUE_BLOCK_SIZE = BigInt(16_777_216)

export async function allocateEmailDequeueSeqs(pool: Pool, jobTeamIds: number[]): Promise<string[]> {
    const indicesByTeam = new Map<number, number[]>()
    jobTeamIds.forEach((teamId, i) => {
        const indices = indicesByTeam.get(teamId)
        if (indices) {
            indices.push(i)
        } else {
            indicesByTeam.set(teamId, [i])
        }
    })
    if (indicesByTeam.size === 0) {
        return []
    }

    const teamIds = [...indicesByTeam.keys()]
    const increments = teamIds.map((id) => indicesByTeam.get(id)!.length)

    const upsertResult = await pool.query<{ team_id: number; counter: string }>(
        `WITH max_counter AS (
             SELECT COALESCE(MAX(counter), 0) AS m FROM cyclotron_email_team_seq
         )
         INSERT INTO cyclotron_email_team_seq (team_id, counter)
         SELECT team_id, increment + (SELECT m FROM max_counter)
         FROM unnest($1::int[], $2::bigint[]) AS t(team_id, increment)
         ON CONFLICT (team_id) DO UPDATE
            SET counter = cyclotron_email_team_seq.counter
                        + (EXCLUDED.counter - (SELECT m FROM max_counter))
         RETURNING team_id, counter`,
        [teamIds, increments]
    )

    const newCounters = new Map<number, bigint>(upsertResult.rows.map((r) => [r.team_id, BigInt(r.counter)]))
    const dequeueSeqs: string[] = new Array(jobTeamIds.length)
    for (const [teamId, indices] of indicesByTeam) {
        const newCounter = newCounters.get(teamId)
        if (newCounter === undefined) {
            throw new Error(`No email counter for team ${teamId} after the UPSERT`)
        }
        teamDequeueSeqs(teamId, newCounter, indices.length).forEach((dequeueSeq, k) => {
            dequeueSeqs[indices[k]] = dequeueSeq
        })
    }
    return dequeueSeqs
}

function teamDequeueSeqs(teamId: number, newCounter: bigint, count: number): string[] {
    const startCounter = newCounter - BigInt(count) + 1n
    const teamIdBigInt = BigInt(teamId)
    return Array.from({ length: count }, (_, k) =>
        ((startCounter + BigInt(k)) * EMAIL_DEQUEUE_BLOCK_SIZE + teamIdBigInt).toString()
    )
}

async function allocateTeamEmailDequeueSeqs(pool: Pool, teamId: number, count: number): Promise<string[]> {
    const updated = await pool.query<{ counter: string }>(
        `UPDATE cyclotron_email_team_seq
         SET counter = counter + $2
         WHERE team_id = $1
         RETURNING counter`,
        [teamId, count]
    )
    if (updated.rows.length === 0) {
        return allocateEmailDequeueSeqs(pool, new Array(count).fill(teamId))
    }
    return teamDequeueSeqs(teamId, BigInt(updated.rows[0].counter), count)
}

export function batchEmailDequeueSeqs(pool: Pool): (teamId: number) => Promise<string> {
    type Waiter = { resolve: (dequeueSeq: string) => void; reject: (error: unknown) => void }
    let waitersByTeam = new Map<number, Waiter[]>()
    const allocateForTeam = async (teamId: number, waiters: Waiter[]): Promise<void> => {
        try {
            const dequeueSeqs = await timeEnqueuePhase('sequence_reserve', 'worker', () =>
                allocateTeamEmailDequeueSeqs(pool, teamId, waiters.length)
            )
            waiters.forEach(({ resolve }, i) => resolve(dequeueSeqs[i]))
        } catch (error) {
            waiters.forEach(({ reject }) => reject(error))
        }
    }
    const flush = (): void => {
        const batch = waitersByTeam
        waitersByTeam = new Map()
        for (const [teamId, waiters] of batch) {
            void allocateForTeam(teamId, waiters)
        }
    }
    return (teamId) =>
        new Promise((resolve, reject) => {
            if (waitersByTeam.size === 0) {
                setImmediate(flush)
            }
            const waiters = waitersByTeam.get(teamId)
            if (waiters) {
                waiters.push({ resolve, reject })
            } else {
                waitersByTeam.set(teamId, [{ resolve, reject }])
            }
        })
}

// Counts Postgres write failures from createJob / bulkCreateJobs *after* input
// validation has passed. Zod parse errors and the overwrite-conflict logical
// error do not increment this counter. The `kind` label splits failures into:
//   - "logical": schema drift, constraint violation, anything that won't fix
//     itself. Any non-zero rate is page-worthy.
//   - "transient": PG / pgbouncer connection issues (matched against
//     isTransientPgError). Brief blips are noise; sustained
//     rate indicates the database is unhealthy.
const dbWriteFailureCounter = new Counter({
    name: 'cdp_cyclotron_v2_db_write_failure',
    help: 'Failed Postgres writes to cyclotron_jobs (input already validated), split by kind=logical|transient.',
    labelNames: ['kind'] as const,
})

const rescheduleSweptCounter = new Counter({
    name: 'cdp_cyclotron_v2_reschedule_parked_swept',
    help: 'Parked cyclotron jobs whose scheduled time was pulled forward by a timing-edit reschedule sweep.',
})

const rescheduleWindowHistogram = new Histogram({
    name: 'cdp_cyclotron_v2_reschedule_parked_window_seconds',
    help: 'Spread window sized for a timing-edit reschedule sweep (observed once per sweep, on the sizing slice).',
    buckets: [300, 600, 1800, 3600, 7200, 14400],
})

const rescheduleFailureCounter = new Counter({
    name: 'cdp_cyclotron_v2_reschedule_parked_failures',
    help: 'Failed reschedule sweep slices, split by kind=logical|transient.',
    labelNames: ['kind'] as const,
})

type EnqueuePhase = 'depth_check' | 'sequence_reserve' | 'insert'
type EnqueueCaller = 'manager' | 'worker'

const enqueuePhaseHistogram = new Histogram({
    name: 'cdp_cyclotron_v2_enqueue_phase_duration_seconds',
    help: 'Time spent in each awaited step of enqueuing cyclotron jobs: the queue depth check, the email dequeue sequence reserve, and the insert.',
    labelNames: ['phase', 'caller'] as const,
    buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60],
})

export async function timeEnqueuePhase<T>(
    phase: EnqueuePhase,
    caller: EnqueueCaller,
    step: () => Promise<T> | T
): Promise<T> {
    const end = enqueuePhaseHistogram.startTimer({ phase, caller })
    try {
        return await step()
    } finally {
        end()
    }
}

const cancelMarkedCounter = new Counter({
    name: 'cdp_cyclotron_v2_cancel_marked',
    help: 'In-flight cyclotron jobs flagged for cancellation, split by the job status at marking time.',
    labelNames: ['status'] as const,
})

/**
 * Thrown when an `overwriteExisting` createJob / bulkCreateJobs hits a row
 * that's still in an active state ('available' or 'running'). Callers should
 * treat this as a "skip and warn" rather than a hard failure — the user is
 * trying to rerun an invocation that's still mid-flight, which the safer
 * default is to refuse.
 */
export class CyclotronJobConflictError extends Error {
    constructor(public readonly conflictingIds: string | string[]) {
        super(
            `Cyclotron job overwrite refused: existing row(s) ${
                Array.isArray(conflictingIds) ? conflictingIds.join(', ') : conflictingIds
            } are in an active state`
        )
        this.name = 'CyclotronJobConflictError'
    }
}

export class CyclotronV2Manager {
    private pool: Pool
    private readonly depthLimit: number
    private readonly depthCheckIntervalMs: number
    private readonly backgroundDepthCheck: boolean
    private depthCheckPromise: Promise<boolean> | null = null
    private depthCheckExpiresAt = 0
    private lastDepthFull: boolean | null = null
    private depthRefresh: Promise<boolean> | null = null
    private readonly depthRefreshSql: string
    private readonly reschedule: {
        floorSeconds: number
        wakeRatePerSecond: number
        minWindowSeconds: number
        maxWindowSeconds: number
        chunkSize: number
        maxChunksPerCall: number
        chunkSleepMs: number
    }

    constructor(config: CyclotronV2ManagerConfig) {
        this.pool = createCyclotronPool('manager', {
            connectionString: config.pool.dbUrl,
            max: config.pool.maxConnections ?? 10,
            idleTimeoutMillis: config.pool.idleTimeoutMs ?? 30000,
        })
        this.depthLimit = config.depthLimit ?? 1_000_000
        this.depthCheckIntervalMs = config.depthCheckIntervalMs ?? 10_000
        this.backgroundDepthCheck = config.backgroundDepthCheck ?? false
        this.depthRefreshSql = `SET LOCAL statement_timeout = ${Math.max(1, Math.floor(this.depthCheckIntervalMs))}; ${cappedQueueDepthSql(this.depthLimit)}`
        this.reschedule = {
            floorSeconds: config.rescheduleFloorSeconds ?? 600,
            wakeRatePerSecond: config.rescheduleWakeRatePerSecond ?? 200,
            minWindowSeconds: config.rescheduleMinWindowSeconds ?? 300,
            maxWindowSeconds: config.rescheduleMaxWindowSeconds ?? 14_400,
            chunkSize: config.rescheduleChunkSize ?? 5_000,
            maxChunksPerCall: config.rescheduleMaxChunksPerCall ?? 20,
            chunkSleepMs: config.rescheduleChunkSleepMs ?? 100,
        }
    }

    async connect(): Promise<void> {
        const client = await this.pool.connect()
        client.release()
    }

    async createJob(input: CyclotronV2JobInit): Promise<string> {
        const job = CyclotronV2JobInitSchema.parse(input)
        await this.insertGuard()

        const id = job.id ?? uuidv7()
        const now = new Date()
        // Rerun re-uses the original invocation_id so lifecycle rows collapse
        // under the same ReplacingMergeTree key. The ON CONFLICT clause resets
        // a prior _terminal_ job row back to 'available' with fresh state. If
        // the existing row is still active ('available' or 'running'), the
        // UPDATE's WHERE fails, the row isn't returned, and we surface that as
        // a skip so the caller can warn rather than silently clobber in-flight
        // work. `transition_count` bumps so the janitor's poison-pill guard
        // still applies across reruns.
        const upsertClause = job.overwriteExisting
            ? `ON CONFLICT (id) DO UPDATE SET
                 status = 'available',
                 priority = EXCLUDED.priority,
                 scheduled = EXCLUDED.scheduled,
                 lock_id = NULL,
                 last_heartbeat = NULL,
                 last_transition = EXCLUDED.last_transition,
                 transition_count = LEAST(cyclotron_jobs.transition_count + 1, ${CYCLOTRON_COUNTER_MAX}),
                 parent_run_id = EXCLUDED.parent_run_id,
                 state = EXCLUDED.state,
                 distinct_id = EXCLUDED.distinct_id,
                 person_id = EXCLUDED.person_id,
                 action_id = EXCLUDED.action_id,
                 cancel_requested_at = NULL
               WHERE cyclotron_jobs.status IN ('completed', 'failed', 'canceled')
               RETURNING id`
            : 'RETURNING id'
        let result: { rows: { id: string }[] }
        try {
            result = await timeEnqueuePhase('insert', 'manager', () =>
                this.pool.query<{ id: string }>(
                    `INSERT INTO cyclotron_jobs
                 (id, team_id, function_id, queue_name, status, priority, scheduled, created,
                  lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
                  parent_run_id, state, distinct_id, person_id, action_id)
                 VALUES ($1, $2, $3, $4, 'available', $5, $6, $7,
                         NULL, NULL, 0, 0, $7,
                         $8, $9, $10, $11, $12)
                 ${upsertClause}`,
                    [
                        id,
                        job.teamId,
                        job.functionId ?? null,
                        job.queueName,
                        job.priority ?? 0,
                        job.scheduled ?? now,
                        now,
                        job.parentRunId ?? null,
                        job.state ?? null,
                        job.distinctId ?? null,
                        job.personId ?? null,
                        job.actionId ?? null,
                    ]
                )
            )
        } catch (err) {
            dbWriteFailureCounter.labels({ kind: isTransientPgError(err) ? 'transient' : 'logical' }).inc()
            throw err
        }
        if (job.overwriteExisting && result.rows.length === 0) {
            // Existing row was in an active state — refuse to clobber.
            throw new CyclotronJobConflictError(id)
        }
        return id
    }

    /**
     * Bulk-insert jobs. If any input is flagged `overwriteExisting`, the entire
     * batch uses `ON CONFLICT (id) DO UPDATE` so existing rows are reset back
     * to 'available' rather than colliding on the primary key. This is how the
     * rerun path re-enqueues an invocation while preserving its
     * `invocation_id` (so lifecycle rows collapse under one ReplacingMergeTree
     * key). Mixing overwrite + non-overwrite in the same batch isn't supported
     * — pre-split into separate calls if you need that.
     */
    async bulkCreateJobs(inputs: CyclotronV2JobInit[]): Promise<string[]> {
        if (inputs.length === 0) {
            return []
        }

        const jobs = inputs.map((input) => CyclotronV2JobInitSchema.parse(input))
        const overwriteExisting = jobs.some((j) => j.overwriteExisting)

        await this.insertGuard()

        const ids: string[] = []
        const teamIds: number[] = []
        const functionIds: (string | null)[] = []
        const queueNames: string[] = []
        const priorities: number[] = []
        const scheduleds: Date[] = []
        const parentRunIds: (string | null)[] = []
        const states: (Buffer | null)[] = []
        const distinctIds: (string | null)[] = []
        const personIds: (string | null)[] = []
        const actionIds: (string | null)[] = []

        const now = new Date()

        for (const job of jobs) {
            const id = job.id ?? uuidv7()
            ids.push(id)
            teamIds.push(job.teamId)
            functionIds.push(job.functionId ?? null)
            queueNames.push(job.queueName)
            priorities.push(job.priority ?? 0)
            scheduleds.push(job.scheduled ?? now)
            parentRunIds.push(job.parentRunId ?? null)
            states.push(job.state ?? null)
            distinctIds.push(job.distinctId ?? null)
            personIds.push(job.personId ?? null)
            actionIds.push(job.actionId ?? null)
        }

        // Fair-dequeue sort key for email-queue jobs. NULL for everything else.
        // Atomically bumps the per-team counter (one UPSERT for the whole batch
        // regardless of size) and then derives a unique dequeue_seq per job.
        const dequeueSeqs = await this.computeEmailDequeueSeqs(jobs)

        const upsertClause = overwriteExisting
            ? `ON CONFLICT (id) DO UPDATE SET
                 status = 'available',
                 priority = EXCLUDED.priority,
                 scheduled = EXCLUDED.scheduled,
                 lock_id = NULL,
                 last_heartbeat = NULL,
                 last_transition = EXCLUDED.last_transition,
                 transition_count = LEAST(cyclotron_jobs.transition_count + 1, ${CYCLOTRON_COUNTER_MAX}),
                 parent_run_id = EXCLUDED.parent_run_id,
                 state = EXCLUDED.state,
                 distinct_id = EXCLUDED.distinct_id,
                 person_id = EXCLUDED.person_id,
                 action_id = EXCLUDED.action_id,
                 dequeue_seq = EXCLUDED.dequeue_seq,
                 cancel_requested_at = NULL
               WHERE cyclotron_jobs.status IN ('completed', 'failed', 'canceled')
               RETURNING id`
            : 'RETURNING id'
        let result: { rows: { id: string }[] }
        try {
            result = await timeEnqueuePhase('insert', 'manager', () =>
                this.pool.query<{ id: string }>(
                    `INSERT INTO cyclotron_jobs
                 (id, team_id, function_id, queue_name, status, priority, scheduled, created,
                  lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
                  parent_run_id, state, distinct_id, person_id, action_id, dequeue_seq)
                 SELECT
                    unnest($1::uuid[]),
                    unnest($2::int[]),
                    unnest($3::uuid[]),
                    unnest($4::text[]),
                    'available'::CyclotronJobStatus,
                    unnest($5::smallint[]),
                    unnest($6::timestamptz[]),
                    $12::timestamptz,
                    NULL::uuid,
                    NULL::timestamptz,
                    0::smallint,
                    0::smallint,
                    $12::timestamptz,
                    unnest($7::text[]),
                    unnest($8::bytea[]),
                    unnest($9::text[]),
                    unnest($10::text[]),
                    unnest($11::text[]),
                    unnest($13::bigint[])
                 ${upsertClause}`,
                    [
                        ids,
                        teamIds,
                        functionIds,
                        queueNames,
                        priorities,
                        scheduleds,
                        parentRunIds,
                        states,
                        distinctIds,
                        personIds,
                        actionIds,
                        now,
                        dequeueSeqs,
                    ]
                )
            )
        } catch (err) {
            dbWriteFailureCounter.labels({ kind: isTransientPgError(err) ? 'transient' : 'logical' }).inc()
            throw err
        }

        if (overwriteExisting) {
            const returnedIds = new Set(result.rows.map((r) => r.id))
            const skipped = ids.filter((id) => !returnedIds.has(id))
            if (skipped.length > 0) {
                throw new CyclotronJobConflictError(skipped)
            }
        }

        return ids
    }

    private async computeEmailDequeueSeqs(jobs: CyclotronV2JobInit[]): Promise<(string | null)[]> {
        const emailIndices = jobs.flatMap((job, i) => (job.queueName === 'email' ? [i] : []))
        const dequeueSeqs: (string | null)[] = new Array(jobs.length).fill(null)
        if (emailIndices.length === 0) {
            return dequeueSeqs
        }
        const emailSeqs = await timeEnqueuePhase('sequence_reserve', 'manager', () =>
            allocateEmailDequeueSeqs(
                this.pool,
                emailIndices.map((i) => jobs[i].teamId)
            )
        )
        emailIndices.forEach((jobIndex, k) => {
            dequeueSeqs[jobIndex] = emailSeqs[k]
        })
        return dequeueSeqs
    }

    // "In flight" = jobs still owned by the queue: parked waits/delays ('available' with a future
    // scheduled time) and jobs a worker currently holds ('running'). Terminal rows don't count.
    // Grouped by action_id so publish impact can say "N runs are parked on step X"; rows without
    // one (freshly enqueued and not yet executed, or predating the lookup column) land in
    // positionUnknown, never silently dropped.
    async countInFlightJobs(teamId: number, functionId: string): Promise<CyclotronV2InFlightCounts> {
        const result = await this.pool.query<{ action_id: string | null; count: number }>(
            `SELECT action_id, COUNT(*)::int AS count FROM cyclotron_jobs
             WHERE team_id = $1 AND function_id = $2 AND status IN ('available', 'running')
             GROUP BY action_id`,
            [teamId, functionId]
        )
        let count = 0
        let positionUnknown = 0
        const byAction: Record<string, number> = {}
        for (const row of result.rows) {
            count += row.count
            if (row.action_id) {
                byAction[row.action_id] = row.count
            } else {
                positionUnknown = row.count
            }
        }
        return { count, byAction, positionUnknown }
    }

    /**
     * Pull forward the wake times of a workflow's parked jobs after a timing
     * edit (issue #66380): jobs parked on one of `actionIds` get
     * `scheduled = LEAST(scheduled, sweepFloor + random() * window)`, so each
     * wakes somewhere inside the window, re-reads the live config, and either
     * advances or re-parks at the recomputed target. Waking early is
     * behaviourally idempotent (the executor's live-timing-edit contract
     * tests), so this never needs to read job state or compute wake times.
     *
     * Two invariants make the sweep safe:
     * - `LEAST` never moves a wake later than its natural time.
     * - Swept rows land at or before `sweepUntil`, and the candidate predicate
     *   is `scheduled > sweepUntil` — so the sweep is idempotent and naturally
     *   terminating, and rows already waking within the window are untouched.
     *
     * The floor keeps the earliest sweep-induced wake beyond the hog flow
     * cache's worst-case staleness (LazyLoader refreshAge + jitter, ~6 min),
     * so a woken job always executes against the post-edit config even on a
     * worker that missed the reload pubsub. The window is sized from the
     * parked count and a wake rate: mass-waking parked jobs at once has
     * dropped jobs in past load spikes, so wakes are trickled instead.
     *
     * Callers slice large sweeps across calls (maxChunksPerCall bounds one
     * call's work) and MUST thread the returned bounds into follow-up calls —
     * resizing the window per slice would re-compress the tail of the spread.
     * Stale bounds (a retry landing after the window largely elapsed) are
     * re-sized instead of honored: honoring them would `LEAST` the remainder
     * into the past and mass-wake it.
     */
    async rescheduleParkedJobs(
        options: CyclotronV2RescheduleParkedOptions
    ): Promise<CyclotronV2RescheduleParkedResult> {
        const { teamId, functionId, actionIds } = options
        if (actionIds.length === 0) {
            throw new Error('rescheduleParkedJobs requires at least one action id')
        }

        try {
            let bounds: { sweepFloor: Date; sweepUntil: Date } | null = null
            const staleBoundsCutoff = new Date(Date.now() + this.reschedule.minWindowSeconds * 1000)
            if (options.sweepFloor && options.sweepUntil && options.sweepUntil > staleBoundsCutoff) {
                // The floor is this sweep's safety property (no sweep-induced wake sooner than
                // floorSeconds from now — the config-cache staleness bound), so it is enforced
                // server-side regardless of what bounds the caller passed: a floor in the past
                // would land the random targets in the past and mass-wake the backlog. Clamping
                // per slice only compresses the tail of the spread, never the predicate, so
                // cross-slice idempotency (scheduled > sweepUntil) is unaffected.
                const minFloor = new Date(Date.now() + this.reschedule.floorSeconds * 1000)
                const sweepFloor = options.sweepFloor > minFloor ? options.sweepFloor : minFloor
                if (sweepFloor < options.sweepUntil) {
                    bounds = { sweepFloor, sweepUntil: options.sweepUntil }
                }
            }
            if (!bounds) {
                if (options.sweepUntil) {
                    logger.warn('Reschedule sweep bounds are stale or unsafe, re-sizing window', {
                        teamId,
                        functionId,
                        sweepUntil: options.sweepUntil.toISOString(),
                    })
                }
                const sized = await this.sizeRescheduleWindow(teamId, functionId, actionIds)
                if (!sized) {
                    const now = new Date()
                    return { swept: 0, remaining: 0, done: true, sweepFloor: now, sweepUntil: now }
                }
                bounds = sized
            }
            const { sweepFloor, sweepUntil } = bounds

            let swept = 0
            for (let chunk = 0; chunk < this.reschedule.maxChunksPerCall; chunk++) {
                if (chunk > 0) {
                    await sleep(this.reschedule.chunkSleepMs)
                }
                const result = await this.pool.query(
                    `WITH candidates AS (
                        SELECT id FROM cyclotron_jobs
                        WHERE team_id = $1 AND function_id = $2 AND status = 'available'
                          AND action_id = ANY($3::text[])
                          AND scheduled > $5
                        LIMIT $6
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE cyclotron_jobs j
                    SET scheduled = LEAST(j.scheduled, $4::timestamptz + random() * ($5::timestamptz - $4::timestamptz))
                    FROM candidates c
                    WHERE j.id = c.id`,
                    [teamId, functionId, actionIds, sweepFloor, sweepUntil, this.reschedule.chunkSize]
                )
                swept += result.rowCount ?? 0
                if ((result.rowCount ?? 0) < this.reschedule.chunkSize) {
                    break
                }
            }
            rescheduleSweptCounter.inc(swept)

            const remainingResult = await this.pool.query<{ count: number }>(
                `SELECT COUNT(*)::int AS count FROM cyclotron_jobs
                 WHERE team_id = $1 AND function_id = $2 AND status = 'available'
                   AND action_id = ANY($3::text[])
                   AND scheduled > $4`,
                [teamId, functionId, actionIds, sweepUntil]
            )
            const remaining = remainingResult.rows[0].count

            logger.info('Reschedule sweep slice completed', {
                teamId,
                functionId,
                actionIds,
                swept,
                remaining,
                sweepFloor: sweepFloor.toISOString(),
                sweepUntil: sweepUntil.toISOString(),
            })

            return { swept, remaining, done: remaining === 0, sweepFloor, sweepUntil }
        } catch (err) {
            rescheduleFailureCounter.labels({ kind: isTransientPgError(err) ? 'transient' : 'logical' }).inc()
            throw err
        }
    }

    /**
     * Flag in-flight jobs for cancellation. This never writes a terminal status
     * itself: the manager has no path to the lifecycle/metric sinks, so the
     * owning worker performs the actual cancellation (terminal status flip plus
     * lifecycle row, metric, and log) when it next observes the job. Parked rows
     * get their wake pulled forward so that happens promptly; rows a worker
     * currently holds are flagged only, never fighting `lock_id`, because the
     * worker's release pulls the wake forward via its cancel-aware scheduled
     * CASE, so they terminate one step later.
     *
     * Chunked like `rescheduleParkedJobs` so one call never updates an
     * unbounded row count; callers loop while `done` is false. Selection
     * deliberately spans queues: a run's job can sit on another queue (e.g.
     * 'email') mid-step and still needs to be cancellable. Callers whose
     * function also owns non-run orchestration jobs exclude those queues via
     * `excludeQueueNames`.
     */
    async cancelJobs(options: CyclotronV2CancelJobsOptions): Promise<CyclotronV2CancelJobsResult> {
        const { teamId, functionId } = options
        const selectorCount = [
            options.jobIds !== undefined,
            options.all === true,
            options.parentRunId !== undefined,
        ].filter(Boolean).length
        if (selectorCount !== 1) {
            throw new Error('cancelJobs requires exactly one selector: jobIds, parentRunId, or all')
        }
        // Rejected rather than treated as unset: the SQL builder below tests truthiness, so an
        // empty string would leave the selector clause empty and silently widen a parent-run
        // cancel to every in-flight job of the workflow.
        if (options.parentRunId !== undefined && options.parentRunId.length === 0) {
            throw new Error('cancelJobs parentRunId must be a non-empty string')
        }

        const jobIds = options.jobIds ? [...new Set(options.jobIds)] : undefined
        if (jobIds && jobIds.length === 0) {
            return { marked: 0, remaining: 0, done: true }
        }

        const params: (number | string | string[])[] = [teamId, functionId]
        let selectorClause = ''
        if (jobIds) {
            params.push(jobIds)
            selectorClause = `AND id = ANY($${params.length}::uuid[])`
        } else if (options.parentRunId) {
            params.push(options.parentRunId)
            selectorClause = `AND parent_run_id = $${params.length}`
        }
        if (options.excludeQueueNames?.length) {
            params.push(options.excludeQueueNames)
            selectorClause += ` AND queue_name != ALL($${params.length}::text[])`
        }

        let marked = 0

        // Parked rows: flag + wake. SKIP LOCKED skips rows a concurrent dequeue
        // is claiming; those turn 'running' and the second UPDATE catches them.
        const chunkLimitParam = params.length + 1
        for (let chunk = 0; chunk < this.reschedule.maxChunksPerCall; chunk++) {
            if (chunk > 0) {
                await sleep(this.reschedule.chunkSleepMs)
            }
            const result = await this.pool.query(
                `WITH candidates AS (
                    SELECT id FROM cyclotron_jobs
                    WHERE team_id = $1 AND function_id = $2 AND status = 'available'
                      AND cancel_requested_at IS NULL
                      ${selectorClause}
                    LIMIT $${chunkLimitParam}
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE cyclotron_jobs j
                SET cancel_requested_at = NOW(), scheduled = LEAST(j.scheduled, NOW())
                FROM candidates c
                WHERE j.id = c.id`,
                [...params, this.reschedule.chunkSize]
            )
            const n = result.rowCount ?? 0
            marked += n
            cancelMarkedCounter.labels({ status: 'available' }).inc(n)
            if (n < this.reschedule.chunkSize) {
                break
            }
        }

        // Rows held by a worker right now: bounded by worker concurrency, so
        // no chunking or wake write needed.
        const runningResult = await this.pool.query(
            `UPDATE cyclotron_jobs
             SET cancel_requested_at = NOW()
             WHERE team_id = $1 AND function_id = $2 AND status = 'running'
               AND cancel_requested_at IS NULL
               ${selectorClause}`,
            params
        )
        const runningMarked = runningResult.rowCount ?? 0
        marked += runningMarked
        cancelMarkedCounter.labels({ status: 'running' }).inc(runningMarked)

        const remainingResult = await this.pool.query<{ count: number }>(
            `SELECT COUNT(*)::int AS count FROM cyclotron_jobs
             WHERE team_id = $1 AND function_id = $2 AND status IN ('available', 'running')
               AND cancel_requested_at IS NULL
               ${selectorClause}`,
            params
        )
        const remaining = remainingResult.rows[0].count

        logger.info('Cancel sweep completed', {
            teamId,
            functionId,
            mode: jobIds ? 'jobIds' : options.parentRunId ? 'parentRunId' : 'all',
            marked,
            remaining,
        })

        return { marked, remaining, done: remaining === 0 }
    }

    /**
     * Size the sweep window for the current parked backlog: floor at
     * `now + floorSeconds`, width `count / wakeRatePerSecond` clamped to
     * [minWindow, maxWindow]. Counts everything beyond the floor — a slight
     * overcount versus the final `scheduled > sweepUntil` predicate, which
     * only widens the window (conservative). Returns null when nothing is
     * parked beyond the floor.
     */
    private async sizeRescheduleWindow(
        teamId: number,
        functionId: string,
        actionIds: string[]
    ): Promise<{ sweepFloor: Date; sweepUntil: Date } | null> {
        const countResult = await this.pool.query<{ count: number }>(
            `SELECT COUNT(*)::int AS count FROM cyclotron_jobs
             WHERE team_id = $1 AND function_id = $2 AND status = 'available'
               AND action_id = ANY($3::text[])
               AND scheduled > NOW() + make_interval(secs => $4)`,
            [teamId, functionId, actionIds, this.reschedule.floorSeconds]
        )
        const count = countResult.rows[0].count
        if (count === 0) {
            return null
        }

        const windowSeconds = Math.min(
            this.reschedule.maxWindowSeconds,
            Math.max(this.reschedule.minWindowSeconds, Math.ceil(count / this.reschedule.wakeRatePerSecond))
        )
        rescheduleWindowHistogram.observe(windowSeconds)

        const sweepFloor = new Date(Date.now() + this.reschedule.floorSeconds * 1000)
        const sweepUntil = new Date(sweepFloor.getTime() + windowSeconds * 1000)
        return { sweepFloor, sweepUntil }
    }

    async disconnect(): Promise<void> {
        await this.pool.end()
    }

    private async insertGuard(): Promise<void> {
        if (await timeEnqueuePhase('depth_check', 'manager', () => this.isFull())) {
            throw new Error(`Cyclotron V2 queue is full (depth limit: ${this.depthLimit})`)
        }
    }

    private isFull(): Promise<boolean> | boolean {
        if (this.backgroundDepthCheck) {
            return this.isFullFromLastDepth()
        }
        if (this.depthCheckPromise && Date.now() < this.depthCheckExpiresAt) {
            return this.depthCheckPromise
        }

        this.depthCheckPromise = this.queryDepth()
        this.depthCheckExpiresAt = Date.now() + this.depthCheckIntervalMs
        return this.depthCheckPromise
    }

    private isFullFromLastDepth(): Promise<boolean> | boolean {
        const now = Date.now()
        if (this.lastDepthFull === null || now >= this.depthCheckExpiresAt + this.depthCheckIntervalMs) {
            return this.refreshDepth()
        }
        if (now >= this.depthCheckExpiresAt) {
            void this.refreshDepth()
        }
        return this.lastDepthFull
    }

    private refreshDepth(): Promise<boolean> {
        if (!this.depthRefresh) {
            this.depthCheckExpiresAt = Date.now() + this.depthCheckIntervalMs
            this.depthRefresh = this.queryDepth(this.depthRefreshSql)
                .then((full) => {
                    this.lastDepthFull = full
                    return full
                })
                .finally(() => {
                    this.depthRefresh = null
                })
        }
        return this.depthRefresh
    }

    private async queryDepth(sql: string = QUEUE_DEPTH_SQL): Promise<boolean> {
        try {
            const result: QueryResult | QueryResult[] = await this.pool.query(sql)
            const depth = Array.isArray(result) ? result[result.length - 1] : result
            const count = parseInt(depth.rows[0].count, 10)
            const full = count >= this.depthLimit

            if (full) {
                logger.warn('Cyclotron V2 queue at capacity', { count, depthLimit: this.depthLimit })
            }

            return full
        } catch (e) {
            logger.error('Cyclotron V2 depth check failed', { error: String(e) })
            return false
        }
    }

    // Wakes parked workflow steps with the outcome of the run they dispatched. Scoped to one team
    // because the caller's token is; see processStepResumes for the per-job outcomes.
    async resumeParkedSteps(teamId: number, resumes: StepResume[]): Promise<Map<string, StepResumeOutcome>> {
        return await processStepResumes(this.pool, resumes, teamId)
    }

    async resumeParkedBatchResolver(options: {
        teamId: number
        functionId: string
        batchJobId: string
    }): Promise<BatchResolverResumeOutcome> {
        return await resumeParkedBatchResolver(this.pool, options)
    }
}
