import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { logger } from '../../../utils/logger'
import { CyclotronV2DequeuedJob, CyclotronV2WorkerConfig } from './types'

interface RawJobRow {
    id: string
    team_id: number
    function_id: string | null
    queue_name: string
    priority: number
    scheduled: Date
    created: Date
    parent_run_id: string | null
    transition_count: number
    state: Buffer | null
    lock_id: string
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

export class CyclotronV2Worker {
    private pool: Pool
    private isConsuming = false
    private lastPollTime = new Date()
    private consumerLoopPromise: Promise<void> | null = null

    private readonly batchMaxSize: number
    private readonly pollDelayMs: number
    private readonly heartbeatTimeoutMs: number
    private readonly includeEmptyBatches: boolean

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
    }

    async connect(processBatch: (jobs: CyclotronV2DequeuedJob[]) => Promise<void>): Promise<void> {
        const client = await this.pool.connect()
        client.release()

        this.isConsuming = true
        this.consumerLoopPromise = this.runConsumerLoop(processBatch)
    }

    private async runConsumerLoop(processBatch: (jobs: CyclotronV2DequeuedJob[]) => Promise<void>): Promise<void> {
        while (this.isConsuming) {
            try {
                this.lastPollTime = new Date()
                const rows = await this.dequeueJobs()

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

    private async dequeueJobs(): Promise<RawJobRow[]> {
        const lockId = uuidv7()
        const result = await this.pool.query<RawJobRow>(
            `WITH available AS (
                SELECT id
                FROM cyclotron_v2_jobs
                WHERE status = 'available'
                  AND queue_name = $1
                  AND scheduled <= NOW()
                ORDER BY priority ASC, scheduled ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            UPDATE cyclotron_v2_jobs
            SET status = 'running',
                lock_id = $3,
                last_heartbeat = NOW(),
                last_transition = NOW(),
                transition_count = transition_count + 1
            FROM available
            WHERE cyclotron_v2_jobs.id = available.id
            RETURNING
                cyclotron_v2_jobs.id,
                cyclotron_v2_jobs.team_id,
                cyclotron_v2_jobs.function_id,
                cyclotron_v2_jobs.queue_name,
                cyclotron_v2_jobs.priority,
                cyclotron_v2_jobs.scheduled,
                cyclotron_v2_jobs.created,
                cyclotron_v2_jobs.parent_run_id,
                cyclotron_v2_jobs.transition_count,
                cyclotron_v2_jobs.state,
                cyclotron_v2_jobs.lock_id`,
            [this.config.queueName, this.batchMaxSize, lockId]
        )
        return result.rows
    }

    private wrapJob(row: RawJobRow): CyclotronV2DequeuedJob {
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
            scheduled: row.scheduled,
            created: row.created,
            parentRunId: row.parent_run_id,
            transitionCount: row.transition_count,
            state: row.state,

            async ack(): Promise<void> {
                releaseGuard('ack')
                await pool.query(
                    `UPDATE cyclotron_v2_jobs
                     SET status = 'completed', lock_id = NULL, last_heartbeat = NULL,
                         last_transition = NOW(), transition_count = transition_count + 1
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async fail(): Promise<void> {
                releaseGuard('fail')
                await pool.query(
                    `UPDATE cyclotron_v2_jobs
                     SET status = 'failed', lock_id = NULL, last_heartbeat = NULL,
                         last_transition = NOW(), transition_count = transition_count + 1
                     WHERE id = $1 AND lock_id = $2`,
                    [row.id, lockId]
                )
            },

            async retry(options?: { delayMs?: number; state?: Buffer | null }): Promise<void> {
                releaseGuard('retry')
                const delayMs = options?.delayMs ?? 0
                const hasStateUpdate = options?.state !== undefined

                if (hasStateUpdate) {
                    await pool.query(
                        `UPDATE cyclotron_v2_jobs
                         SET status = 'available', lock_id = NULL, last_heartbeat = NULL,
                             last_transition = NOW(), transition_count = transition_count + 1,
                             scheduled = NOW() + make_interval(secs => $3::double precision / 1000),
                             state = $4
                         WHERE id = $1 AND lock_id = $2`,
                        [row.id, lockId, delayMs, options!.state ?? null]
                    )
                } else {
                    await pool.query(
                        `UPDATE cyclotron_v2_jobs
                         SET status = 'available', lock_id = NULL, last_heartbeat = NULL,
                             last_transition = NOW(), transition_count = transition_count + 1,
                             scheduled = NOW() + make_interval(secs => $3::double precision / 1000)
                         WHERE id = $1 AND lock_id = $2`,
                        [row.id, lockId, delayMs]
                    )
                }
            },

            async cancel(): Promise<void> {
                releaseGuard('cancel')
                await pool.query(
                    `UPDATE cyclotron_v2_jobs
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
                    `UPDATE cyclotron_v2_jobs
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

    async disconnect(): Promise<void> {
        this.isConsuming = false
        if (this.consumerLoopPromise) {
            await this.consumerLoopPromise
        }
        await this.pool.end()
    }
}
