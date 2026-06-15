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
    help: 'Number of poison pill jobs dead-lettered by the janitor',
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

const deadLetterDepthGauge = new Gauge({
    name: 'cdp_cyclotron_v2_dead_letter_depth',
    help: 'Number of jobs parked in the dead-letter table',
})

const poisoningPausedGauge = new Gauge({
    name: 'cdp_cyclotron_v2_janitor_poisoning_paused',
    help: 'Whether dead-lettering is paused because stalls look fleet-wide (1) or active (0)',
})

export class CyclotronV2Janitor {
    private pool: Pool
    private intervalHandle: ReturnType<typeof setInterval> | null = null

    private readonly cleanupBatchSize: number
    private readonly cleanupIntervalMs: number
    private readonly stallTimeoutMs: number
    private readonly maxTouchCount: number
    private readonly cleanupGraceMs: number
    private readonly fleetStallRatioThreshold: number
    private readonly fleetHealthWindowMs: number
    private readonly fleetMinStalledCount: number

    private completionSamples: { ts: number; completed: number }[] = []

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
        this.fleetStallRatioThreshold = config.fleetStallRatioThreshold ?? 0.5
        this.fleetHealthWindowMs = config.fleetHealthWindowMs ?? 300000
        this.fleetMinStalledCount = config.fleetMinStalledCount ?? 5
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
        const deletedCounts = await this.cleanupTerminalJobs()
        const deleted = Object.values(deletedCounts).reduce((a, b) => a + b, 0)

        this.recordCompletionSample(deletedCounts['completed'] ?? 0)

        // Gate dead-lettering on fleet health: during an outage every in-flight
        // job stalls at once, and giving up on them would drop work that a
        // recovered fleet could still run. Only reset/retry in that state.
        const stalledNow = await this.countStalledRunningJobs()
        const poisoningPaused = this.isFleetUnhealthy(stalledNow)
        poisoningPausedGauge.set(poisoningPaused ? 1 : 0)

        let poisonedIds: string[] = []
        if (poisoningPaused) {
            logger.warn('CyclotronV2Janitor poisoning paused, fleet unhealthy', {
                stalledNow,
                completedInWindow: this.completedInWindow(),
                fleetStallRatioThreshold: this.fleetStallRatioThreshold,
            })
        } else {
            poisonedIds = await this.deadLetterPoisonPills()
        }

        const stalled = await this.resetStalledJobs()
        const depths = await this.measureQueueDepths()
        const dlqDepth = await this.measureDeadLetterDepth()

        janitorRunCounter.inc()

        return { deleted, stalled, poisoned: poisonedIds.length, poisonedIds, poisoningPaused, depths, dlqDepth }
    }

    private async cleanupTerminalJobs(): Promise<Record<string, number>> {
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

        return counts
    }

    private recordCompletionSample(completed: number): void {
        const now = Date.now()
        this.completionSamples.push({ ts: now, completed })
        this.completionSamples = this.completionSamples.filter((s) => s.ts > now - this.fleetHealthWindowMs)
    }

    private completedInWindow(): number {
        return this.completionSamples.reduce((acc, s) => acc + s.completed, 0)
    }

    private async countStalledRunningJobs(): Promise<number> {
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)
        const result = await this.pool.query<{ count: string }>(
            `SELECT COUNT(*) AS count FROM cyclotron_jobs
             WHERE status = 'running' AND COALESCE(last_heartbeat, $1) <= $1`,
            [heartbeatCutoff]
        )
        return parseInt(result.rows[0].count, 10)
    }

    // Stalls are fleet-wide when many jobs are stalled at once AND stalls
    // dominate completions over the rolling window. Steady-state stalls are
    // ~0, so a healthy fleet with one bad job stays well below both bars.
    private isFleetUnhealthy(stalledNow: number): boolean {
        if (stalledNow < this.fleetMinStalledCount) {
            return false
        }
        const completed = this.completedInWindow()
        return stalledNow / (stalledNow + completed) > this.fleetStallRatioThreshold
    }

    // Poison pills: running jobs with stale heartbeats that have been reset
    // too many times. Move the full row into the dead-letter table (preserved
    // and replay-ready) rather than failing it, which the cleanup pass would
    // permanently delete.
    private async deadLetterPoisonPills(): Promise<string[]> {
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)
        const reason = `poison pill detected based on a stall timeout of ${this.stallTimeoutMs}ms and max touch count of ${this.maxTouchCount}`

        const result = await this.pool.query<{ id: string }>(
            `WITH poison AS (
                SELECT id
                FROM cyclotron_jobs
                WHERE status = 'running'
                  AND COALESCE(last_heartbeat, $1) <= $1
                  AND janitor_touch_count >= $2
                FOR UPDATE SKIP LOCKED
            ),
            moved AS (
                DELETE FROM cyclotron_jobs
                USING poison
                WHERE cyclotron_jobs.id = poison.id
                RETURNING cyclotron_jobs.*
            )
            INSERT INTO cyclotron_jobs_dead_letter
                (id, team_id, function_id, original_queue_name, original_status, priority, scheduled, created,
                 last_heartbeat, janitor_touch_count, transition_count, last_transition, parent_run_id, state,
                 distinct_id, person_id, action_id, reason, dlq_time)
            SELECT id, team_id, function_id, queue_name, status, priority, scheduled, created,
                   last_heartbeat, janitor_touch_count, transition_count, last_transition, parent_run_id, state,
                   distinct_id, person_id, action_id, $3, NOW()
            FROM moved
            RETURNING id`,
            [heartbeatCutoff, this.maxTouchCount, reason]
        )

        const ids = result.rows.map((r) => r.id)
        if (ids.length > 0) {
            janitorPoisonedCounter.inc(ids.length)
            logger.warn('CyclotronV2Janitor dead-lettered poison pill jobs', { count: ids.length, ids })
        }

        return ids
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

    async measureDeadLetterDepth(): Promise<number> {
        const result = await this.pool.query<{ count: string }>(
            `SELECT COUNT(*) AS count FROM cyclotron_jobs_dead_letter`
        )
        const depth = parseInt(result.rows[0].count, 10)
        deadLetterDepthGauge.set(depth)
        return depth
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
