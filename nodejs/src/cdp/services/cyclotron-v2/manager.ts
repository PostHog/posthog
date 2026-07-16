import { Pool } from 'pg'
import { Counter, Histogram } from 'prom-client'
import { v7 as uuidv7 } from 'uuid'

import { isTransientPgError } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { sleep } from '~/common/utils/utils'

import {
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

/**
 * Atomically bump the per-team email counter and return the formatted
 * `dequeue_seq` string for one new email job. Exported because the worker's
 * `reschedule()` path also needs to assign `dequeue_seq` when a hog/hogflow
 * job is re-routed into the email queue — without this, those rows land with
 * `NULL dequeue_seq` and bypass the per-team interleave (`NULLS FIRST` would
 * drain them ahead of any fair-ordered rows).
 *
 * A team's *first ever* email starts at `MAX(counter) + 1` across the table
 * (Hatchet's `p_max_assigned` pattern), so a brand-new tenant can't enqueue a
 * burst that gets free priority over established tenants' in-flight emails.
 * Continuing tenants just increment their own counter as before. `COALESCE`
 * handles the empty-table cold-start (`MAX = NULL` → starting point of 0).
 *
 * For bulk inserts of multiple email jobs at once, `bulkCreateJobs` uses its
 * own batched UPSERT for efficiency rather than calling this in a loop.
 */
export async function assignEmailDequeueSeq(pool: Pool, teamId: number): Promise<string> {
    const result = await pool.query<{ counter: string }>(
        `INSERT INTO cyclotron_email_team_seq (team_id, counter)
         VALUES ($1, COALESCE((SELECT MAX(counter) FROM cyclotron_email_team_seq), 0) + 1)
         ON CONFLICT (team_id) DO UPDATE
            SET counter = cyclotron_email_team_seq.counter + 1
         RETURNING counter`,
        [teamId]
    )
    const counter = BigInt(result.rows[0].counter)
    // pg accepts BIGINT as string to avoid JS number precision loss
    return (counter * EMAIL_DEQUEUE_BLOCK_SIZE + BigInt(teamId)).toString()
}

// Counts Postgres write failures from createJob / bulkCreateJobs *after* input
// validation has passed. Zod parse errors and the overwrite-conflict logical
// error do not increment this counter. The `kind` label splits failures into:
//   - "logical": schema drift, constraint violation, anything that won't fix
//     itself. Any non-zero rate is page-worthy.
//   - "transient": PG / pgbouncer connection issues (matched against
//     POSTGRES_UNAVAILABLE_ERROR_MESSAGES). Brief blips are noise; sustained
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
    private depthCheckPromise: Promise<boolean> | null = null
    private depthCheckExpiresAt = 0
    private readonly rescheduleFloorSeconds: number
    private readonly rescheduleWakeRatePerSecond: number
    private readonly rescheduleMinWindowSeconds: number
    private readonly rescheduleMaxWindowSeconds: number
    private readonly rescheduleChunkSize: number
    private readonly rescheduleMaxChunksPerCall: number
    private readonly rescheduleChunkSleepMs: number

    constructor(config: CyclotronV2ManagerConfig) {
        this.pool = new Pool({
            connectionString: config.pool.dbUrl,
            max: config.pool.maxConnections ?? 10,
            idleTimeoutMillis: config.pool.idleTimeoutMs ?? 30000,
        })
        this.depthLimit = config.depthLimit ?? 1_000_000
        this.depthCheckIntervalMs = config.depthCheckIntervalMs ?? 10_000
        this.rescheduleFloorSeconds = config.rescheduleFloorSeconds ?? 600
        this.rescheduleWakeRatePerSecond = config.rescheduleWakeRatePerSecond ?? 200
        this.rescheduleMinWindowSeconds = config.rescheduleMinWindowSeconds ?? 300
        this.rescheduleMaxWindowSeconds = config.rescheduleMaxWindowSeconds ?? 14_400
        this.rescheduleChunkSize = config.rescheduleChunkSize ?? 5_000
        this.rescheduleMaxChunksPerCall = config.rescheduleMaxChunksPerCall ?? 20
        this.rescheduleChunkSleepMs = config.rescheduleChunkSleepMs ?? 100
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
                 transition_count = cyclotron_jobs.transition_count + 1,
                 parent_run_id = EXCLUDED.parent_run_id,
                 state = EXCLUDED.state,
                 distinct_id = EXCLUDED.distinct_id,
                 person_id = EXCLUDED.person_id,
                 action_id = EXCLUDED.action_id
               WHERE cyclotron_jobs.status IN ('completed', 'failed', 'canceled')
               RETURNING id`
            : 'RETURNING id'
        let result: { rows: { id: string }[] }
        try {
            result = await this.pool.query<{ id: string }>(
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
                 transition_count = cyclotron_jobs.transition_count + 1,
                 parent_run_id = EXCLUDED.parent_run_id,
                 state = EXCLUDED.state,
                 distinct_id = EXCLUDED.distinct_id,
                 person_id = EXCLUDED.person_id,
                 action_id = EXCLUDED.action_id,
                 dequeue_seq = EXCLUDED.dequeue_seq
               WHERE cyclotron_jobs.status IN ('completed', 'failed', 'canceled')
               RETURNING id`
            : 'RETURNING id'
        let result: { rows: { id: string }[] }
        try {
            result = await this.pool.query<{ id: string }>(
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

    /**
     * Compute the per-job `dequeue_seq` array for a batch of jobs.
     *
     * Email-queue jobs get `counter * BLOCK_SIZE + team_id` where `counter`
     * is the team's monotonic per-team sequence number. Sorting ascending by
     * dequeue_seq interleaves teams: each team's first job sorts together,
     * then each team's second job, etc.
     *
     * Non-email jobs get NULL (leaves the existing FIFO ordering untouched).
     *
     * One UPSERT for the whole batch regardless of job count — per-team
     * counters bump by the count of email jobs from that team in this batch,
     * and we derive each job's individual counter value in memory.
     *
     * A team's first-ever email starts at `MAX(counter) + 1` across the table
     * (Hatchet's `p_max_assigned` pattern), so a new tenant joining the
     * system can't enqueue a burst that gets free priority over established
     * tenants — established tenants are already at `MAX`, so a new tenant's
     * batch slots in at the same level and the round-robin interleaves them
     * by team_id from there. Continuing teams just keep incrementing.
     */
    private async computeEmailDequeueSeqs(jobs: CyclotronV2JobInit[]): Promise<(string | null)[]> {
        const indicesByTeam = new Map<number, number[]>()
        for (let i = 0; i < jobs.length; i++) {
            if (jobs[i].queueName !== 'email') {
                continue
            }
            const indices = indicesByTeam.get(jobs[i].teamId)
            if (indices) {
                indices.push(i)
            } else {
                indicesByTeam.set(jobs[i].teamId, [i])
            }
        }

        const dequeueSeqs: (string | null)[] = new Array(jobs.length).fill(null)
        if (indicesByTeam.size === 0) {
            return dequeueSeqs
        }

        const teamIds = [...indicesByTeam.keys()]
        const increments = teamIds.map((id) => indicesByTeam.get(id)!.length)

        // Atomic per-team UPSERT. Concurrent inserts for different teams don't
        // contend; same-team inserts serialize briefly on the row. Returns the
        // new counter value per team — we then derive individual job counters
        // by subtracting back through the batch.
        //
        // Hatchet `p_max_assigned`: new-team rows insert at `MAX + increment`
        // so they slot in next to established teams. Existing-team rows still
        // add just `increment` (we subtract the MAX shift back out in the ON
        // CONFLICT branch). MAX is computed once per batch via the CTE.
        const upsertResult = await this.pool.query<{ team_id: number; counter: string }>(
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

        for (const [teamId, indices] of indicesByTeam) {
            const newCounter = newCounters.get(teamId)
            if (newCounter === undefined) {
                // Should never happen — every team in indicesByTeam was UPSERTed.
                logger.error('Missing counter after UPSERT in computeEmailDequeueSeqs', { teamId })
                continue
            }
            const startCounter = newCounter - BigInt(indices.length) + 1n
            const teamIdBigInt = BigInt(teamId)
            for (let k = 0; k < indices.length; k++) {
                const counterForThisJob = startCounter + BigInt(k)
                // pg accepts BIGINT as string to avoid JS number precision loss
                dequeueSeqs[indices[k]] = (counterForThisJob * EMAIL_DEQUEUE_BLOCK_SIZE + teamIdBigInt).toString()
            }
        }

        return dequeueSeqs
    }

    // "In flight" = jobs still owned by the queue: parked waits/delays ('available' with a future
    // scheduled time) and jobs a worker currently holds ('running'). Terminal rows don't count.
    async countInFlightJobs(teamId: number, functionId: string): Promise<number> {
        const result = await this.pool.query<{ count: number }>(
            `SELECT COUNT(*)::int AS count FROM cyclotron_jobs
             WHERE team_id = $1 AND function_id = $2 AND status IN ('available', 'running')`,
            [teamId, functionId]
        )
        return result.rows[0].count
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
            const staleBoundsCutoff = new Date(Date.now() + this.rescheduleMinWindowSeconds * 1000)
            if (options.sweepFloor && options.sweepUntil && options.sweepUntil > staleBoundsCutoff) {
                // The floor is this sweep's safety property (no sweep-induced wake sooner than
                // floorSeconds from now — the config-cache staleness bound), so it is enforced
                // server-side regardless of what bounds the caller passed: a floor in the past
                // would land the random targets in the past and mass-wake the backlog. Clamping
                // per slice only compresses the tail of the spread, never the predicate, so
                // cross-slice idempotency (scheduled > sweepUntil) is unaffected.
                const minFloor = new Date(Date.now() + this.rescheduleFloorSeconds * 1000)
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
            for (let chunk = 0; chunk < this.rescheduleMaxChunksPerCall; chunk++) {
                if (chunk > 0) {
                    await sleep(this.rescheduleChunkSleepMs)
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
                    [teamId, functionId, actionIds, sweepFloor, sweepUntil, this.rescheduleChunkSize]
                )
                swept += result.rowCount ?? 0
                if ((result.rowCount ?? 0) < this.rescheduleChunkSize) {
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
            [teamId, functionId, actionIds, this.rescheduleFloorSeconds]
        )
        const count = countResult.rows[0].count
        if (count === 0) {
            return null
        }

        const windowSeconds = Math.min(
            this.rescheduleMaxWindowSeconds,
            Math.max(this.rescheduleMinWindowSeconds, Math.ceil(count / this.rescheduleWakeRatePerSecond))
        )
        rescheduleWindowHistogram.observe(windowSeconds)

        const sweepFloor = new Date(Date.now() + this.rescheduleFloorSeconds * 1000)
        const sweepUntil = new Date(sweepFloor.getTime() + windowSeconds * 1000)
        return { sweepFloor, sweepUntil }
    }

    async disconnect(): Promise<void> {
        await this.pool.end()
    }

    private async insertGuard(): Promise<void> {
        if (await this.isFull()) {
            throw new Error(`Cyclotron V2 queue is full (depth limit: ${this.depthLimit})`)
        }
    }

    private isFull(): Promise<boolean> {
        if (this.depthCheckPromise && Date.now() < this.depthCheckExpiresAt) {
            return this.depthCheckPromise
        }

        this.depthCheckPromise = this.queryDepth()
        this.depthCheckExpiresAt = Date.now() + this.depthCheckIntervalMs
        return this.depthCheckPromise
    }

    private async queryDepth(): Promise<boolean> {
        try {
            const result = await this.pool.query(
                `SELECT COUNT(*) AS count FROM cyclotron_jobs
                 WHERE status = 'available' AND scheduled <= NOW()`
            )
            const count = parseInt(result.rows[0].count, 10)
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
}
