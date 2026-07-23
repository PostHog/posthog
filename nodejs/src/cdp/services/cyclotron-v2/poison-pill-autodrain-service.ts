import { Pool } from 'pg'

import { logger } from '~/common/utils/logger'

import { HealthCheckResult, HealthCheckResultOk, PluginServerService, PluginsServerConfig } from '../../../types'
import { CyclotronPoisonPillAutodrain } from './poison-pill-autodrain'

/**
 * Service wrapper for the poison-pill autodrain worker. Owns the cyclotron-node
 * Postgres pool so the inner worker stays a plain, unit-testable class.
 *
 * Runs on a timer interval inside the cyclotron-v2 janitor deployment (the
 * capability rides along on the janitor mode), gated by
 * `CYCLOTRON_POISON_PILL_AUTODRAIN_ENABLED` — no separate deployment. Same
 * co-located-singleton pattern as `appManagementSingleton` in `cdp_api`.
 *
 * The retry loop is entirely Postgres (release parked poison rows back onto their
 * queue), so there is no ClickHouse dependency — the janitor parks poison pills in
 * place rather than deleting them, and this service moves them back.
 */
export class CyclotronPoisonPillAutodrainService {
    private worker: CyclotronPoisonPillAutodrain
    private pool: Pool

    constructor(config: PluginsServerConfig) {
        if (!config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CYCLOTRON_NODE_DATABASE_URL is required for CyclotronPoisonPillAutodrainService')
        }

        this.pool = new Pool({
            connectionString: config.CYCLOTRON_NODE_DATABASE_URL,
            max: config.CYCLOTRON_NODE_MAX_CONNECTIONS ?? 5,
            idleTimeoutMillis: config.CYCLOTRON_NODE_IDLE_TIMEOUT_MS ?? 30000,
        })

        this.worker = new CyclotronPoisonPillAutodrain(this.pool, {
            intervalMs: config.CYCLOTRON_POISON_PILL_AUTODRAIN_INTERVAL_MS,
            maxAttempts: config.CYCLOTRON_POISON_PILL_AUTODRAIN_MAX_ATTEMPTS,
            batchSize: config.CYCLOTRON_POISON_PILL_AUTODRAIN_GROUP_BATCH,
        })
    }

    async start(): Promise<void> {
        await this.worker.start()
        logger.info('CyclotronPoisonPillAutodrainService started')
    }

    async stop(): Promise<void> {
        this.worker.stop()
        await this.pool.end()
    }

    isHealthy(): HealthCheckResult {
        // Best-effort — always OK. This service is co-located in the janitor pod, and
        // the pod's /_health fails (503 → restart) if ANY registered service's
        // healthcheck errors. The autodrain is a non-critical background poller
        // releasing already-durable parked poison rows; a stalled interval must not
        // restart the critical janitor sharing this process. Liveness is observed via
        // its metrics/logs (cdp_cyclotron_v2_autodrain_*), not the pod probe.
        if (!this.worker.isRunning()) {
            logger.warn(
                'CyclotronPoisonPillAutodrain interval is not running (health stays OK — co-located with janitor)'
            )
        }
        return new HealthCheckResultOk()
    }

    get service(): PluginServerService {
        return {
            id: 'cdp-cyclotron-v2-poison-pill-autodrain',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy(),
        }
    }
}
