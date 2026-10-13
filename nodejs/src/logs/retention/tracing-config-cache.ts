import { trace } from '@opentelemetry/api'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

const REFRESH_MS = 30_000

/**
 * Ingestion default when a team has no `tracing_teamtracingconfig` row; must match
 * `DEFAULT_TRACES_RETENTION_DAYS` in `products/tracing/backend/models.py`.
 */
export const DEFAULT_TRACES_RETENTION_DAYS = 14

type CacheEntry = {
    retentionDays: number
    fetchedAtMs: number
}

const tracingConfigInstrumentOpts = { measureTime: false, sendException: false } as const

/**
 * Per-team default span retention, read from the tracing product's team extension.
 *
 * Kept out of `TeamManager` on purpose: that query is on the hot path of every consumer,
 * including events ingestion, so widening it for one traces setting is the wrong trade.
 */
export class TracingConfigCache {
    private cache = new Map<number, CacheEntry>()

    constructor(private postgres: PostgresRouter) {}

    public async getRetentionDays(teamId: number): Promise<number> {
        return instrumentFn(
            {
                key: 'tracesIngestion.retention.getRetentionDays',
                ...tracingConfigInstrumentOpts,
                getLoggingContext: () => ({ team_id: teamId }),
            },
            async () => {
                const now = Date.now()
                const existing = this.cache.get(teamId)
                if (existing && now - existing.fetchedAtMs < REFRESH_MS) {
                    trace.getActiveSpan()?.setAttributes({
                        'traces.retention.cache_hit': true,
                        'traces.retention.default_days': existing.retentionDays,
                    })
                    return existing.retentionDays
                }
                let retentionDays: number
                try {
                    retentionDays = await this.fetchRetentionDays(teamId)
                } catch (error) {
                    if (!existing && error instanceof DependencyUnavailableError) {
                        throw error
                    }
                    // Serve the last-known value when we have one; the stale `fetchedAtMs` retries on the next message.
                    logger.warn('[traces-retention] tracing config fetch failed — falling back', {
                        teamId,
                        error: String(error),
                    })
                    trace.getActiveSpan()?.setAttributes({
                        'traces.retention.fetch_failed': true,
                        'traces.retention.served_stale': Boolean(existing),
                    })
                    return existing?.retentionDays ?? DEFAULT_TRACES_RETENTION_DAYS
                }
                this.cache.set(teamId, { retentionDays, fetchedAtMs: now })
                trace.getActiveSpan()?.setAttributes({
                    'traces.retention.cache_hit': false,
                    'traces.retention.default_days': retentionDays,
                })
                return retentionDays
            }
        )
    }

    private async fetchRetentionDays(teamId: number): Promise<number> {
        const res = await this.postgres.query<{ retention_days: number }>(
            PostgresUse.COMMON_READ,
            `SELECT retention_days
             FROM tracing_teamtracingconfig
             WHERE team_id = $1`,
            [teamId],
            'traces-tracing-config-fetch'
        )
        // A team that never opened the tracing settings has no row yet.
        const stored = res.rows[0]?.retention_days
        return typeof stored === 'number' && stored > 0 ? stored : DEFAULT_TRACES_RETENTION_DAYS
    }
}
