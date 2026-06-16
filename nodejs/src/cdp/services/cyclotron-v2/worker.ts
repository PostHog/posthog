import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { logger } from '../../../utils/logger'
import {
    CyclotronV2DequeuedJob,
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
        this.fairDequeue = config.fairDequeue ?? false
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
     * Cheap pre-check that returns true iff any job is currently dequeueable
     * from this worker's queue. Used by rate-limited subclasses to skip the
     * token-bucket claim entirely on idle polls, so the limiter stays silent
     * when there's nothing to send.
     *
     * Hits the same partial index as `dequeueJobs` (`idx_cyclotron_jobs_dequeue`,
     * filtered on `status = 'available'`), so the query is sub-millisecond and
     * strictly cheaper than the `UPDATE ... SKIP LOCKED` we'd otherwise run.
     */
    protected async hasWork(): Promise<boolean> {
        const result = await this.pool.query(
            `SELECT 1 FROM cyclotron_jobs
             WHERE status = 'available'
               AND queue_name = $1
               AND scheduled <= NOW()
             LIMIT 1`,
            [this.config.queueName]
        )
        return result.rowCount !== null && result.rowCount > 0
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
