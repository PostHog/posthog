import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { BackgroundRefresher } from './background-refresher'
import { logger } from './logger'

// Redis key the DmatKillSwitch polls. Set to any non-empty value to disable dmat
// ingestion globally; delete to re-enable. Takes effect within `REFRESH_INTERVAL_MS`.
//
//     redis-cli set dmat_kill_switch 1     # disable
//     redis-cli del dmat_kill_switch       # re-enable
//
// See docs/internal/dmat-deployment.md for the runbook.
export const DMAT_KILL_SWITCH_REDIS_KEY = 'dmat_kill_switch'

const REFRESH_INTERVAL_MS = 1000 * 60

/**
 * Global runtime kill switch for dmat ingestion.
 *
 * Mirrors the `EventIngestionRestrictionManager` pattern — polls Redis on a background
 * refresher so the hot path can call a synchronous `isDisabled()` getter without doing
 * IO per event. When the switch is on, `MaterializedColumnSlotManager` returns an empty
 * slot set for every team, which makes `extractDynamicMaterializedColumns` produce no
 * dmat column writes. HogQL reads are unaffected — this only stops *new writes* so a
 * detected ingestion-side bug stops accumulating bad data while operators investigate.
 */
export class DmatKillSwitch {
    private redisPool: GenericPool<Redis>
    private refresher: BackgroundRefresher<boolean>

    constructor(redisPool: GenericPool<Redis>) {
        this.redisPool = redisPool
        this.refresher = new BackgroundRefresher(
            () => this.fetchDisabledFromRedis(),
            REFRESH_INTERVAL_MS,
            // Swallow refresh errors and stay enabled. We treat "Redis is down" as
            // safer than "fail open" — but the alternative (defaulting to disabled on
            // Redis failure) would silently kill all ingestion every time Redis hiccups.
            (error) => logger.error('DmatKillSwitch: failed to refresh kill switch state', { error })
        )

        void this.refresher.get().catch((error) => {
            logger.error('DmatKillSwitch: failed to initialize', { error })
        })
    }

    /**
     * Synchronous, hot-path-safe. Returns `true` if dmat ingestion should be disabled.
     * Triggers a background refresh if the cached value is stale, but does not block.
     * If Redis has never been reached successfully, returns `false` (enabled by default).
     */
    public isDisabled(): boolean {
        return this.refresher.tryGet() ?? false
    }

    /** Force an immediate refresh — used by tests to avoid waiting for the timer. */
    public async forceRefresh(): Promise<void> {
        await this.refresher.refresh()
    }

    private async fetchDisabledFromRedis(): Promise<boolean> {
        const client = await this.redisPool.acquire()
        try {
            const value = await client.get(DMAT_KILL_SWITCH_REDIS_KEY)
            return value !== null && value !== ''
        } finally {
            await this.redisPool.release(client)
        }
    }
}
