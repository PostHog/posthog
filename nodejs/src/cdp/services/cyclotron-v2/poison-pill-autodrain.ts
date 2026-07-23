import { Pool } from 'pg'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

const autodrainReleasedCounter = new Counter({
    name: 'cdp_cyclotron_v2_autodrain_released_total',
    help: 'Parked poison-pill jobs released back to their queue for another attempt',
})

const autodrainErrorsCounter = new Counter({
    name: 'cdp_cyclotron_v2_autodrain_errors_total',
    help: 'Autodrain release ticks that failed',
})

export interface CyclotronPoisonPillAutodrainConfig {
    intervalMs: number
    // A parked poison pill is released at most this many times before it is left
    // parked for good (dead-lettered). Mirrors the old CH-discovery attempts cap.
    maxAttempts: number
    // Max parked jobs released per tick, so one tick can't flood the queues.
    batchSize: number
}

export interface AutodrainRunResult {
    released: number
}

/**
 * Releases parked poison-pill jobs back onto their queue for another attempt.
 *
 * When the janitor gives up on a poison pill it PARKS the job in place — leaves the
 * real cyclotron_jobs row, sets `scheduled` far in the future so no worker dequeues
 * it, and stamps `poison_retry_count`. This service periodically moves such rows'
 * `scheduled` back to now (incrementing the count), so a worker re-runs the real job.
 *
 * Everything happens in Postgres, so there is no ClickHouse-visibility lag in the
 * loop: the release is a single atomic UPDATE guarded by `scheduled = 'infinity'`
 * and `FOR UPDATE SKIP LOCKED`, so a job can't be released twice (no duplicate
 * execution) even across concurrent ticks or pods, and once released it drops out
 * of the parked set until it re-poisons. `poison_retry_count < maxAttempts` bounds
 * retries; beyond that the row stays parked (dead-letter).
 */
export class CyclotronPoisonPillAutodrain {
    private intervalHandle: ReturnType<typeof setInterval> | null = null

    constructor(
        private pool: Pool,
        private config: CyclotronPoisonPillAutodrainConfig
    ) {}

    async start(): Promise<void> {
        this.intervalHandle = setInterval(() => {
            this.runOnce().catch((err) => {
                logger.error('CyclotronPoisonPillAutodrain run error', { error: String(err) })
            })
        }, this.config.intervalMs)

        // Run immediately on start, but never let a failed first tick reject start():
        // this service is co-located in the janitor process and the serviceLoaders are
        // awaited together, so a rejection here would crash the shared pod. The interval
        // is already scheduled, so the next tick retries.
        await this.runOnce().catch((err) => {
            logger.error('CyclotronPoisonPillAutodrain initial run error', { error: String(err) })
        })
    }

    async runOnce(): Promise<AutodrainRunResult> {
        try {
            // Release parked poison pills back to their queue. `scheduled = 'infinity'`
            // matches only currently-parked rows: a row released earlier this cycle has
            // scheduled = now (a real timestamp) and is not re-matched, so it cannot be
            // released twice. FOR UPDATE SKIP LOCKED makes concurrent ticks/pods disjoint.
            const result = await this.pool.query<{ id: string }>(
                `UPDATE cyclotron_jobs
                 SET scheduled = NOW(), poison_retry_count = poison_retry_count + 1
                 WHERE id IN (
                     SELECT id FROM cyclotron_jobs
                     WHERE poison_retry_count IS NOT NULL
                       AND poison_retry_count < $1
                       AND status = 'available'
                       AND scheduled = 'infinity'
                     ORDER BY last_transition ASC
                     LIMIT $2
                     FOR UPDATE SKIP LOCKED
                 )
                 RETURNING id`,
                [this.config.maxAttempts, this.config.batchSize]
            )
            const released = result.rowCount ?? 0
            autodrainReleasedCounter.inc(released)
            if (released > 0) {
                logger.info('CyclotronPoisonPillAutodrain released parked poison pills', { released })
            }
            return { released }
        } catch (err) {
            autodrainErrorsCounter.inc()
            logger.error('CyclotronPoisonPillAutodrain release failed', {
                error: err instanceof Error ? err.message : String(err),
            })
            return { released: 0 }
        }
    }

    isRunning(): boolean {
        return this.intervalHandle !== null
    }

    stop(): void {
        if (this.intervalHandle) {
            clearInterval(this.intervalHandle)
            this.intervalHandle = null
        }
    }
}
