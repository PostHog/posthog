import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { logger } from '../../../utils/logger'
import { CyclotronV2JobInit, CyclotronV2ManagerConfig } from './types'

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

    async createJob(job: CyclotronV2JobInit): Promise<string> {
        await this.insertGuard()

        const id = job.id ?? uuidv7()
        const now = new Date()
        await this.pool.query(
            `INSERT INTO cyclotron_jobs
             (id, team_id, function_id, queue_name, status, priority, scheduled, created,
              lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
              parent_run_id, state)
             VALUES ($1, $2, $3, $4, 'available', $5, $6, $7,
                     NULL, NULL, 0, 0, $7,
                     $8, $9)`,
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
            ]
        )
        return id
    }

    async bulkCreateJobs(jobs: CyclotronV2JobInit[]): Promise<string[]> {
        if (jobs.length === 0) {
            return []
        }

        await this.insertGuard()

        const ids: string[] = []
        const teamIds: number[] = []
        const functionIds: (string | null)[] = []
        const queueNames: string[] = []
        const priorities: number[] = []
        const scheduleds: Date[] = []
        const parentRunIds: (string | null)[] = []
        const states: (Buffer | null)[] = []

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
        }

        await this.pool.query(
            `INSERT INTO cyclotron_jobs
             (id, team_id, function_id, queue_name, status, priority, scheduled, created,
              lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
              parent_run_id, state)
             SELECT
                unnest($1::uuid[]),
                unnest($2::int[]),
                unnest($3::uuid[]),
                unnest($4::text[]),
                'available'::CyclotronJobStatus,
                unnest($5::smallint[]),
                unnest($6::timestamptz[]),
                $9::timestamptz,
                NULL::uuid,
                NULL::timestamptz,
                0::smallint,
                0::smallint,
                $9::timestamptz,
                unnest($7::text[]),
                unnest($8::bytea[])`,
            [ids, teamIds, functionIds, queueNames, priorities, scheduleds, parentRunIds, states, now]
        )

        return ids
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
