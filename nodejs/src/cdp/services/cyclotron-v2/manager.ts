import { Pool } from 'pg'
import { Counter } from 'prom-client'
import { v7 as uuidv7 } from 'uuid'

import { isTransientPgError } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { CyclotronV2JobInit, CyclotronV2JobInitSchema, CyclotronV2ManagerConfig } from './types'

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

    constructor(config: CyclotronV2ManagerConfig) {
        this.pool = new Pool({
            connectionString: config.pool.dbUrl,
            max: config.pool.maxConnections ?? 10,
            idleTimeoutMillis: config.pool.idleTimeoutMs ?? 30000,
        })
        this.depthLimit = config.depthLimit ?? 1_000_000
        this.depthCheckIntervalMs = config.depthCheckIntervalMs ?? 10_000
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
                    unnest($11::text[])
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
     * Re-insert dead-lettered jobs into cyclotron_jobs on their original queue
     * so they run again. Pass explicit ids, or omit to replay everything in
     * the dead-letter table. The DELETE + INSERT runs as one statement, so a
     * conflicting live row aborts the whole replay and the DLQ row survives.
     */
    async replayDeadLetterJobs(ids?: string[]): Promise<string[]> {
        const result = await this.pool.query<{ id: string }>(
            `WITH to_replay AS (
                DELETE FROM cyclotron_jobs_dead_letter
                WHERE $1::uuid[] IS NULL OR id = ANY($1)
                RETURNING *
            )
            INSERT INTO cyclotron_jobs
                (id, team_id, function_id, queue_name, status, priority, scheduled, created,
                 lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
                 parent_run_id, state, distinct_id, person_id, action_id)
            SELECT id, team_id, function_id, original_queue_name, 'available', priority, NOW(), created,
                   NULL, NULL, 0, transition_count, NOW(),
                   parent_run_id, state, distinct_id, person_id, action_id
            FROM to_replay
            RETURNING id`,
            [ids ?? null]
        )

        const replayedIds = result.rows.map((r) => r.id)
        if (replayedIds.length > 0) {
            logger.info('Cyclotron V2 replayed dead-lettered jobs', { count: replayedIds.length, ids: replayedIds })
        }
        return replayedIds
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
