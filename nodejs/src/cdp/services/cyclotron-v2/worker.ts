import { DateTime } from 'luxon'
import { Pool, PoolClient } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { logger } from '~/common/utils/logger'

import { assignEmailDequeueSeq } from './manager'
import {
    CyclotronV2BulkCreateAndCheckInInput,
    CyclotronV2DequeuedJob,
    CyclotronV2JobInit,
    CyclotronV2JobInitSchema,
    CyclotronV2RescheduleOptions,
    CyclotronV2RescheduleOptionsSchema,
    CyclotronV2WorkerConfig,
} from './types'

export interface RawJobRow {
    id: string
    team_id: number
    function_id: string | null
    queue_name: string
    priority: number
    scheduled: string
    created: string
    parent_run_id: string | null
    transition_count: number
    state: Buffer | null
    distinct_id: string | null
    person_id: string | null
    action_id: string | null
    lock_id: string
}

export function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Insert N new jobs within an open transaction. Mirrors the bulk-insert shape
 * from `CyclotronV2Manager.bulkCreateJobs` but runs on a caller-provided
 * client so the inserts can be wrapped in the same transaction as a sibling
 * UPDATE (used by `bulkCreateAndCheckIn`).
 *
 * Intentionally narrower than manager.bulkCreateJobs: no `overwriteExisting`
 * path, no email-queue `dequeue_seq` computation (the resolver enqueues
 * children onto 'hogflow', not 'email'). Email re-routing happens later via
 * the worker's reschedule path which already handles dequeue_seq assignment.
 */
async function insertNewJobsInTx(client: PoolClient, newJobs: CyclotronV2JobInit[]): Promise<string[]> {
    if (newJobs.length === 0) {
        return []
    }

    const now = new Date()
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

    for (const job of newJobs) {
        ids.push(job.id ?? uuidv7())
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

    await client.query(
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
            unnest($11::text[])`,
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

    return ids
}

/**
 * Update the current worker's job row to reflect the chosen disposition
 * (reschedule for next page / ack / fail). Mirrors the SQL shapes used by
 * the wrapper's `ack`, `fail`, and `reschedule` methods, but runs in a
 * caller-provided transaction so it can be atomic with sibling inserts.
 *
 * Throws if the UPDATE doesn't match exactly one row. The `WHERE lock_id`
 * filter can match zero rows if the janitor reassigns the lock between
 * dequeue and commit (stall-recovery race) — without this guard the child
 * inserts would commit while the self UPDATE silently no-ops, leaving the
 * cursor un-advanced for the new lock-holder to replay.
 */
async function updateSelfInTx(
    client: PoolClient,
    jobId: string,
    lockId: string,
    disposition: CyclotronV2BulkCreateAndCheckInInput['selfDisposition']
): Promise<void> {
    if (disposition.kind === 'ack') {
        const result = await client.query(
            `UPDATE cyclotron_jobs
             SET status = 'completed', lock_id = NULL, last_heartbeat = NULL,
                 last_transition = NOW(), transition_count = transition_count + 1
             WHERE id = $1 AND lock_id = $2`,
            [jobId, lockId]
        )
        assertSelfRowAffected(result.rowCount, jobId, 'ack')
        return
    }
    if (disposition.kind === 'fail') {
        const result = await client.query(
            `UPDATE cyclotron_jobs
             SET status = 'failed', lock_id = NULL, last_heartbeat = NULL,
                 last_transition = NOW(), transition_count = transition_count + 1
             WHERE id = $1 AND lock_id = $2`,
            [jobId, lockId]
        )
        assertSelfRowAffected(result.rowCount, jobId, 'fail')
        return
    }
    // reschedule
    const scheduled = disposition.scheduledAt ?? new Date()
    const setClauses = [
        `status = 'available'`,
        `lock_id = NULL`,
        `last_heartbeat = NULL`,
        `last_transition = NOW()`,
        `transition_count = transition_count + 1`,
        `scheduled = $3`,
    ]
    const params: any[] = [jobId, lockId, scheduled]
    if (disposition.state !== undefined) {
        params.push(disposition.state ?? null)
        setClauses.push(`state = $${params.length}`)
    }
    const result = await client.query(
        `UPDATE cyclotron_jobs SET ${setClauses.join(', ')}
         WHERE id = $1 AND lock_id = $2`,
        params
    )
    assertSelfRowAffected(result.rowCount, jobId, 'reschedule')
}

function assertSelfRowAffected(rowCount: number | null, jobId: string, kind: string): void {
    if (rowCount !== 1) {
        throw new Error(
            `bulkCreateAndCheckIn(${kind}) self UPDATE matched ${rowCount} rows for job ${jobId} — lock_id may have been reassigned`
        )
    }
}

export class CyclotronV2Worker {
    private pool: Pool
    protected isConsuming = false
    protected lastPollTime = new Date()
    private consumerLoopPromise: Promise<void> | null = null

    protected readonly batchMaxSize: number
    protected readonly pollDelayMs: number
    private readonly heartbeatTimeoutMs: number
    protected readonly includeEmptyBatches: boolean
    protected readonly fairDequeue: boolean

    constructor(private config: CyclotronV2WorkerConfig) {
        this.pool = new Pool({
            connectionString: config.pool.dbUrl,
            max: config.pool.maxConnections ?? 10,
            idleTimeoutMillis: config.pool.idleTimeoutMs ?? 30000,
        })
        this.batchMaxSize = config.batchMaxSize ?? 100
        this.pollDelayMs = config.pollDelayMs ?? 50
        this.heartbeatTimeoutMs = config.heartbeatTimeoutMs ?? 30000
        this.includeEmptyBatches = config.includeEmptyBatches ?? false
        // Fair (per-team round-robin) dequeue is the email queue's ordering.
        // `dequeue_seq` is only ever assigned for email jobs (see
        // CyclotronV2Manager), so deriving this from the queue name keeps the
        // worker's ORDER BY in lockstep with where the sort key actually exists.
        this.fairDequeue = config.queueName === 'email'
    }

    async connect(processBatch: (jobs: CyclotronV2DequeuedJob[]) => Promise<void>): Promise<void> {
        const client = await this.pool.connect()
        client.release()

        this.isConsuming = true
        this.consumerLoopPromise = this.runConsumerLoop(processBatch)
    }

    protected async runConsumerLoop(processBatch: (jobs: CyclotronV2DequeuedJob[]) => Promise<void>): Promise<void> {
        while (this.isConsuming) {
            try {
                this.lastPollTime = new Date()
                const rows = this.fairDequeue ? await this.fairDequeueJobs() : await this.dequeueJobs()

                if (rows.length === 0) {
                    if (this.includeEmptyBatches) {
                        await processBatch([])
                    }
                    await sleep(this.pollDelayMs)
                    continue
                }

                const jobs = rows.map((row) => this.wrapJob(row))
                await processBatch(jobs)
            } catch (err) {
                logger.error('CyclotronV2Worker consumer loop error', { error: String(err) })
                await sleep(this.pollDelayMs)
            }
        }
    }

    /**
     * Cheap pre-check that returns how many jobs are currently dequeueable from
     * this worker's queue, capped at `limit`. Used by rate-limited subclasses
     * to size their token-bucket claim to "exactly what we plan to dequeue"
     * instead of always claiming the bucket's full capacity — keeps unused
     * tokens in the bucket when traffic is sparse and a single job per poll is
     * what we end up dequeuing.
     *
     * Hits the same partial index as `dequeueJobs` (`idx_cyclotron_jobs_dequeue`,
     * filtered on `status = 'available'`), so the query is sub-millisecond and
     * strictly cheaper than the `UPDATE ... SKIP LOCKED` we'd otherwise run.
     * A short race exists between this count and the subsequent dequeue —
     * concurrent pods may grab some rows in the gap via `SKIP LOCKED` — so
     * `dequeueJobs` can return fewer rows than counted. That's bounded by
     * concurrency × poll rate and rate-limiter refill absorbs the slack.
     */
    protected async countWork(limit: number): Promise<number> {
        const result = await this.pool.query<{ n: number }>(
            `SELECT COUNT(*)::int AS n FROM (
                 SELECT 1 FROM cyclotron_jobs
                 WHERE status = 'available'
                   AND queue_name = $1
                   AND scheduled <= NOW()
                 LIMIT $2
             ) sub`,
            [this.config.queueName, limit]
        )
        return result.rows[0].n
    }

    protected async dequeueJobs(limit: number = this.batchMaxSize): Promise<RawJobRow[]> {
        const lockId = uuidv7()
        const result = await this.pool.query<RawJobRow>(
            `WITH available AS (
                SELECT id
                FROM cyclotron_jobs
                WHERE status = 'available'
                  AND queue_name = $1
                  AND scheduled <= NOW()
                ORDER BY priority ASC, scheduled ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            UPDATE cyclotron_jobs
            SET status = 'running',
                lock_id = $3,
                last_heartbeat = NOW(),
                last_transition = NOW(),
                transition_count = transition_count + 1
            FROM available
            WHERE cyclotron_jobs.id = available.id
            RETURNING
                cyclotron_jobs.id,
                cyclotron_jobs.team_id,
                cyclotron_jobs.function_id,
                cyclotron_jobs.queue_name,
                cyclotron_jobs.priority,
                cyclotron_jobs.scheduled,
                cyclotron_jobs.created,
                cyclotron_jobs.parent_run_id,
                cyclotron_jobs.transition_count,
                cyclotron_jobs.state,
                cyclotron_jobs.distinct_id,
                cyclotron_jobs.person_id,
                cyclotron_jobs.action_id,
                cyclotron_jobs.lock_id`,
            [this.config.queueName, limit, lockId]
        )
        // UPDATE...RETURNING doesn't preserve the CTE's ORDER BY,
        // so re-sort to maintain priority ordering within the batch
        // TODO: Do we care about this in reality?
        return result.rows.sort(
            (a, b) => a.priority - b.priority || new Date(a.scheduled).getTime() - new Date(b.scheduled).getTime()
        )
    }

    /**
     * Fair dequeue: orders by the precomputed `dequeue_seq` so jobs interleave
     * across tenants instead of being strict FIFO. The sort key is assigned at
     * insert time (see `CyclotronV2Manager.bulkCreateJobs` and the helper
     * `cyclotron_email_team_seq`); this method just reads them back in order.
     *
     * Hits the partial index `idx_cyclotron_jobs_email_fair_dequeue` (only
     * indexes email-queue rows with status='available'). NULLS FIRST drains
     * any pre-migration legacy rows ahead of new fair-ordered ones.
     *
     * Email-specific by intent — but mechanically just "ORDER BY a different
     * column", so the SQL shape mirrors `dequeueJobs` exactly. Kept as a
     * separate method so non-fair callers can read `dequeueJobs` end-to-end
     * without following a conditional or an indirection.
     */
    protected async fairDequeueJobs(limit: number = this.batchMaxSize): Promise<RawJobRow[]> {
        const lockId = uuidv7()
        const result = await this.pool.query<RawJobRow>(
            `WITH available AS (
                SELECT id
                FROM cyclotron_jobs
                WHERE status = 'available'
                  AND queue_name = $1
                  AND scheduled <= NOW()
                ORDER BY dequeue_seq ASC NULLS FIRST
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            UPDATE cyclotron_jobs
            SET status = 'running',
                lock_id = $3,
                last_heartbeat = NOW(),
                last_transition = NOW(),
                transition_count = transition_count + 1
            FROM available
            WHERE cyclotron_jobs.id = available.id
            RETURNING
                cyclotron_jobs.id,
                cyclotron_jobs.team_id,
                cyclotron_jobs.function_id,
                cyclotron_jobs.queue_name,
                cyclotron_jobs.priority,
                cyclotron_jobs.scheduled,
                cyclotron_jobs.created,
                cyclotron_jobs.parent_run_id,
                cyclotron_jobs.transition_count,
                cyclotron_jobs.state,
                cyclotron_jobs.distinct_id,
                cyclotron_jobs.person_id,
                cyclotron_jobs.action_id,
                cyclotron_jobs.lock_id`,
            [this.config.queueName, limit, lockId]
        )
        // Within-batch order is undefined (UPDATE...RETURNING doesn't preserve
        // the CTE's ORDER BY), but the fairness guarantee is *across* batches:
        // the CTE picks the rows with the lowest dequeue_seq values, so a
        // small-tenant job never gets stuck behind a large-tenant backlog.
        return result.rows
    }

    protected wrapJob(row: RawJobRow): CyclotronV2DequeuedJob {
        const pool = this.pool
        const lockId = row.lock_id
        let released = false

        const releaseGuard = (method: string) => {
            if (released) {
                throw new Error(`Job ${row.id} already released, cannot call ${method}`)
            }
            released = true
        }

        return {
            id: row.id,
            teamId: row.team_id,
            functionId: row.function_id,
            queueName: row.queue_name,
            priority: row.priority,
            scheduled: DateTime.fromISO(row.scheduled, { zone: 'utc' }),
            created: DateTime.fromISO(row.created, { zone: 'utc' }),
            parentRunId: row.parent_run_id,
            transitionCount: row.transition_count,
            state: row.state,
            distinctId: row.distinct_id,
            personId: row.person_id,
            actionId: row.action_id,

            async ack(): Promise<void> {
                releaseGuard('ack')
                await pool.query(
                    `UPDATE cyclotron_jobs
                     SET status = 'completed', lock_id = NULL, last_heartbeat = NULL,
                         last_transition = NOW(), transition_count = transition_count + 1
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async fail(): Promise<void> {
                releaseGuard('fail')
                await pool.query(
                    `UPDATE cyclotron_jobs
                     SET status = 'failed', lock_id = NULL, last_heartbeat = NULL,
                         last_transition = NOW(), transition_count = transition_count + 1
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async reschedule(input?: CyclotronV2RescheduleOptions): Promise<void> {
                releaseGuard('reschedule')
                const options = input ? CyclotronV2RescheduleOptionsSchema.parse(input) : undefined
                const scheduled = options?.scheduledAt ?? new Date()

                const setClauses = [
                    `status = 'available'`,
                    `lock_id = NULL`,
                    `last_heartbeat = NULL`,
                    `last_transition = NOW()`,
                    `transition_count = transition_count + 1`,
                    `scheduled = $3`,
                ]
                const params: any[] = [row.id, lockId, scheduled]

                if (options?.state !== undefined) {
                    params.push(options.state ?? null)
                    setClauses.push(`state = $${params.length}`)
                }
                if (options?.distinctId !== undefined) {
                    params.push(options.distinctId ?? null)
                    setClauses.push(`distinct_id = $${params.length}`)
                }
                if (options?.personId !== undefined) {
                    params.push(options.personId ?? null)
                    setClauses.push(`person_id = $${params.length}`)
                }
                if (options?.actionId !== undefined) {
                    params.push(options.actionId ?? null)
                    setClauses.push(`action_id = $${params.length}`)
                }
                if (options?.queueName !== undefined) {
                    params.push(options.queueName)
                    setClauses.push(`queue_name = $${params.length}`)
                }

                // Cross-queue routing into the email queue: assign a fresh
                // dequeue_seq so the row participates in fair ordering. Without
                // this, hogflow → email re-routing (via job.reschedule({
                // queueName: 'email' })) lands the row with NULL dequeue_seq,
                // which `NULLS FIRST` drains ahead of every fair-ordered row —
                // defeating the per-team interleave for the most common email
                // path. Skipped when the row was already on the email queue,
                // so existing fair-ordered rows keep their place after retry/
                // reschedule without bumping the counter.
                if (options?.queueName === 'email' && row.queue_name !== 'email') {
                    const dequeueSeq = await assignEmailDequeueSeq(pool, row.team_id)
                    params.push(dequeueSeq)
                    setClauses.push(`dequeue_seq = $${params.length}`)
                }

                await pool.query(
                    `UPDATE cyclotron_jobs SET ${setClauses.join(', ')}
                     WHERE id = $1 AND lock_id = $2`,
                    params
                )
            },

            async cancel(): Promise<void> {
                releaseGuard('cancel')
                await pool.query(
                    `UPDATE cyclotron_jobs
                     SET status = 'canceled', lock_id = NULL, last_heartbeat = NULL,
                         last_transition = NOW(), transition_count = transition_count + 1
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async heartbeat(): Promise<void> {
                if (released) {
                    throw new Error(`Job ${row.id} already released, cannot heartbeat`)
                }
                await pool.query(
                    `UPDATE cyclotron_jobs
                     SET last_heartbeat = NOW()
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async bulkCreateAndCheckIn(input: CyclotronV2BulkCreateAndCheckInInput): Promise<{ newJobIds: string[] }> {
                releaseGuard('bulkCreateAndCheckIn')

                // Validate new jobs up front, outside the TX, so a malformed
                // input doesn't burn a connection slot mid-transaction.
                const newJobs: CyclotronV2JobInit[] = input.newJobs.map((j) => CyclotronV2JobInitSchema.parse(j))

                const client = await pool.connect()
                try {
                    await client.query('BEGIN')

                    const newJobIds = await insertNewJobsInTx(client, newJobs)
                    await updateSelfInTx(client, row.id, lockId, input.selfDisposition)

                    await client.query('COMMIT')
                    return { newJobIds }
                } catch (err) {
                    try {
                        await client.query('ROLLBACK')
                    } catch (rollbackErr) {
                        logger.warn('bulkCreateAndCheckIn rollback failed', {
                            error: String(rollbackErr),
                            originalError: String(err),
                        })
                    }
                    throw err
                } finally {
                    client.release()
                }
            },
        }
    }

    isHealthy(): boolean {
        return this.isConsuming && Date.now() - this.lastPollTime.getTime() < this.heartbeatTimeoutMs
    }

    async stopConsuming(): Promise<void> {
        this.isConsuming = false
        if (this.consumerLoopPromise) {
            await this.consumerLoopPromise
            this.consumerLoopPromise = null
        }
    }

    async disconnect(): Promise<void> {
        await this.stopConsuming()
        await this.pool.end()
    }
}
