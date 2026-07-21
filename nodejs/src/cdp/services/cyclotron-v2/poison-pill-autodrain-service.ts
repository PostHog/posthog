import { ClickHouseClient, createClient as createClickHouseClient } from '@clickhouse/client'
import https from 'https'

import { logger } from '~/common/utils/logger'

import { HealthCheckResult, HealthCheckResultOk, PluginServerService, PluginsServerConfig } from '../../../types'
import { RerunJobManager } from '../../rerun/rerun-job.manager'
import { CyclotronPoisonPillAutodrain } from './poison-pill-autodrain'

/**
 * Service wrapper for the poison-pill autodrain worker. Owns the ClickHouse
 * client (for discovery) and the `RerunJobManager` (for the re-enqueue) so the
 * inner worker stays a plain, unit-testable class.
 *
 * Runs on a timer interval inside the cyclotron-v2 janitor deployment (the
 * capability rides along on the janitor mode), gated by
 * `CYCLOTRON_POISON_PILL_AUTODRAIN_ENABLED` — no separate deployment. Same
 * co-located-singleton pattern as `appManagementSingleton` in `cdp_api`.
 */
export class CyclotronPoisonPillAutodrainService {
    private worker: CyclotronPoisonPillAutodrain
    private clickhouse: ClickHouseClient
    private rerunManager: RerunJobManager

    constructor(config: PluginsServerConfig) {
        if (!config.CYCLOTRON_NODE_DATABASE_URL) {
            throw new Error('CYCLOTRON_NODE_DATABASE_URL is required for CyclotronPoisonPillAutodrainService')
        }

        // Dedicated ClickHouse client for discovery. Internal ClickHouse uses
        // self-signed certs with a hostname mismatch, same as the rerun worker's
        // paginator client.
        const chScheme = config.CLICKHOUSE_SECURE ? 'https' : 'http'
        const chPort = config.CLICKHOUSE_SECURE ? 8443 : 8123
        this.clickhouse = createClickHouseClient({
            url: `${chScheme}://${config.CLICKHOUSE_HOST}:${chPort}`,
            username: config.CLICKHOUSE_USER,
            password: config.CLICKHOUSE_PASSWORD || undefined,
            database: config.CLICKHOUSE_DATABASE,
            request_timeout: 60_000,
            max_open_connections: 10,
            ...(config.CLICKHOUSE_SECURE
                ? {
                      http_agent: new https.Agent({ rejectUnauthorized: false, keepAlive: true, maxSockets: 10 }), // nosemgrep: problem-based-packs.insecure-transport.js-node.bypass-tls-verification.bypass-tls-verification
                  }
                : {}),
        })

        this.rerunManager = new RerunJobManager({
            dbUrl: config.CYCLOTRON_NODE_DATABASE_URL,
            maxConnections: config.CYCLOTRON_NODE_MAX_CONNECTIONS,
            idleTimeoutMs: config.CYCLOTRON_NODE_IDLE_TIMEOUT_MS,
            maxCount: config.HOG_INVOCATION_RERUN_MAX_COUNT,
        })

        this.worker = new CyclotronPoisonPillAutodrain(this.clickhouse, this.rerunManager, {
            intervalMs: config.CYCLOTRON_POISON_PILL_AUTODRAIN_INTERVAL_MS,
            windowHours: config.CYCLOTRON_POISON_PILL_AUTODRAIN_WINDOW_HOURS,
            maxAttempts: config.CYCLOTRON_POISON_PILL_AUTODRAIN_MAX_ATTEMPTS,
            groupBatch: config.CYCLOTRON_POISON_PILL_AUTODRAIN_GROUP_BATCH,
            maxCountPerGroup: config.CYCLOTRON_POISON_PILL_AUTODRAIN_MAX_COUNT_PER_GROUP,
        })
    }

    async start(): Promise<void> {
        // Eagerly probe the cyclotron-node pool before the first tick, but never
        // let a boot-time blip reject start(): this service is co-located in the
        // janitor pod and the serviceLoaders are awaited together (Promise.all),
        // so a rejection here would crash the shared pod — the critical janitor
        // included. The pool connects lazily on first query, and the worker's
        // interval retries (its runOnce is itself wrapped in a catch), so a
        // transient Postgres failure at boot must not take the pod down.
        try {
            await this.rerunManager.connect()
        } catch (err) {
            logger.warn('CyclotronPoisonPillAutodrainService: pool connect failed at boot, retrying on tick', {
                error: String(err),
            })
        }
        await this.worker.start()
        logger.info('CyclotronPoisonPillAutodrainService started')
    }

    async stop(): Promise<void> {
        this.worker.stop()
        await this.rerunManager.disconnect()
        await this.clickhouse.close()
    }

    isHealthy(): HealthCheckResult {
        // Best-effort — always OK. This service is co-located in the janitor pod,
        // and the pod's /_health fails (503 → restart) if ANY registered service's
        // healthcheck errors. The autodrain is a non-critical background poller
        // recovering already-durable poison-pill rows; a stalled interval must not
        // restart the critical janitor sharing this process. Liveness is observed
        // via its metrics/logs (cdp_cyclotron_v2_autodrain_*), not the pod probe.
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
