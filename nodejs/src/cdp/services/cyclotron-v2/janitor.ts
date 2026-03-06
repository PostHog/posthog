import { Pool } from 'pg'
import { Counter, Gauge } from 'prom-client'

import { logger } from '../../../utils/logger'
import { CyclotronV2CleanupResult, CyclotronV2JanitorConfig } from './types'

const janitorDeletedCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_deleted',
    help: 'Number of terminal jobs cleaned up by the janitor',
    labelNames: ['status'],
})

const janitorStalledCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_stalled',
    help: 'Number of stalled jobs reset by the janitor',
})

const janitorPoisonedCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_poisoned',
    help: 'Number of poison pill jobs failed by the janitor',
})

const janitorRunCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_runs',
    help: 'Number of janitor cleanup runs completed',
})

const queueDepthGauge = new Gauge({
    name: 'cdp_cyclotron_v2_queue_depth',
    help: 'Number of available jobs per queue',
    labelNames: ['queue'],
})

export class CyclotronV2Janitor {
    private pool: Pool
    private intervalHandle: ReturnType<typeof setInterval> | null = null

    private readonly cleanupBatchSize: number
    private readonly cleanupIntervalMs: number
    private readonly stallTimeoutMs: number
    private readonly maxTouchCount: number
    private readonly cleanupGraceMs: number

    constructor(config: CyclotronV2JanitorConfig) {
        this.pool = new Pool({
            connectionString: config.pool.dbUrl,
            max: config.pool.maxConnections ?? 5,
            idleTimeoutMillis: config.pool.idleTimeoutMs ?? 30000,
        })
        this.cleanupBatchSize = config.cleanupBatchSize ?? 10000
        this.cleanupIntervalMs = config.cleanupIntervalMs ?? 10000
        this.stallTimeoutMs = config.stallTimeoutMs ?? 30000
        this.maxTouchCount = config.maxTouchCount ?? 3
        this.cleanupGraceMs = config.cleanupGraceMs ?? 10000
    }

    async start(): Promise<void> {
        const client = await this.pool.connect()
        client.release()

        this.intervalHandle = setInterval(() => {
            this.runOnce().catch((err) => {
                logger.error('CyclotronV2Janitor run error', { error: String(err) })
            })
        }, this.cleanupIntervalMs)

        // Run immediately on start
        await this.runOnce()
    }

    async runOnce(): Promise<CyclotronV2CleanupResult> {
        const deleted = await this.cleanupTerminalJobs()
        const poisoned = await this.failPoisonPills()
        const stalled = await this.resetStalledJobs()
        const depths = await this.measureQueueDepths()

        janitorRunCounter.inc()

        return { deleted, stalled, poisoned, depths }
    }

    private async cleanupTerminalJobs(): Promise<number> {
        const cutoff = new Date(Date.now() - this.cleanupGraceMs)

        const result = await this.pool.query<{ status: string; count: string }>(
            `WITH to_delete AS (
                SELECT id
                FROM cyclotron_jobs
                WHERE status IN ('completed', 'failed', 'canceled')
                  AND last_transition < $1
                ORDER BY last_transition ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            DELETE FROM cyclotron_jobs
            USING to_delete
            WHERE cyclotron_jobs.id = to_delete.id
            RETURNING cyclotron_jobs.status::text`,
            [cutoff, this.cleanupBatchSize]
        )

        let total = 0
        const counts: Record<string, number> = {}
        for (const row of result.rows) {
            counts[row.status] = (counts[row.status] ?? 0) + 1
            total++
        }

        for (const [status, count] of Object.entries(counts)) {
            janitorDeletedCounter.inc({ status }, count)
        }

        if (total > 0) {
            logger.info('CyclotronV2Janitor cleaned up terminal jobs', { counts, total })
        }

        return total
    }

    private async failPoisonPills(): Promise<number> {
        // Poison pills: running jobs with stale heartbeats that have been reset too many times
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)

        const result = await this.pool.query(
            `UPDATE cyclotron_jobs
             SET status = 'failed', lock_id = NULL, last_heartbeat = NULL,
                 last_transition = NOW(), transition_count = transition_count + 1
             WHERE id IN (
                 SELECT id
                 FROM cyclotron_jobs
                 WHERE status = 'running'
                   AND COALESCE(last_heartbeat, $1) <= $1
                   AND janitor_touch_count >= $2
                 FOR UPDATE SKIP LOCKED
             )`,
            [heartbeatCutoff, this.maxTouchCount]
        )

        const count = result.rowCount ?? 0
        if (count > 0) {
            janitorPoisonedCounter.inc(count)
            logger.warn('CyclotronV2Janitor failed poison pill jobs', { count })
        }

        return count
    }

    private async resetStalledJobs(): Promise<number> {
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)

        const result = await this.pool.query(
            `WITH stalled AS (
                SELECT id
                FROM cyclotron_jobs
                WHERE status = 'running'
                  AND COALESCE(last_heartbeat, $1) <= $1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE cyclotron_jobs
            SET status = 'available', lock_id = NULL, last_heartbeat = NULL,
                janitor_touch_count = janitor_touch_count + 1
            FROM stalled
            WHERE cyclotron_jobs.id = stalled.id`,
            [heartbeatCutoff]
        )

        const count = result.rowCount ?? 0
        if (count > 0) {
            janitorStalledCounter.inc(count)
            logger.info('CyclotronV2Janitor reset stalled jobs', { count })
        }

        return count
    }

    async measureQueueDepths(): Promise<Map<string, number>> {
        const result = await this.pool.query<{ queue_name: string; count: string }>(
            `SELECT queue_name, COUNT(*) as count
             FROM cyclotron_jobs
             WHERE status = 'available' AND scheduled <= NOW()
             GROUP BY queue_name`
        )

        const depths = new Map<string, number>()
        for (const row of result.rows) {
            const count = parseInt(row.count, 10)
            depths.set(row.queue_name, count)
            queueDepthGauge.labels({ queue: row.queue_name }).set(count)
        }

        return depths
    }

    isRunning(): boolean {
        return this.intervalHandle !== null
    }

    async stop(): Promise<void> {
        if (this.intervalHandle) {
            clearInterval(this.intervalHandle)
            this.intervalHandle = null
        }
        await this.pool.end()
    }
}
