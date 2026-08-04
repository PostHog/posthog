import { trace } from '@opentelemetry/api'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import { MAX_ENABLED_RETENTION_RULES, type RetentionRuleRow, compileRetentionRuleSet } from './compile-retention-rules'
import type { CompiledRetentionRuleSet } from './evaluate-retention'

const REFRESH_MS = 30_000

const retentionCacheInstrumentOpts = { measureTime: false, sendException: false } as const

type CacheEntry = {
    compiled: CompiledRetentionRuleSet
    versionWatermark: number
    fetchedAtMs: number
}

export class RetentionRulesCache {
    private cache = new Map<number, CacheEntry>()

    constructor(private postgres: PostgresRouter) {}

    public async getCompiledRuleSet(teamId: number): Promise<CompiledRetentionRuleSet> {
        return instrumentFn(
            {
                key: 'logsIngestion.retention.getCompiledRuleSet',
                ...retentionCacheInstrumentOpts,
                getLoggingContext: () => ({ team_id: teamId }),
            },
            async () => {
                const now = Date.now()
                const existing = this.cache.get(teamId)
                if (existing && now - existing.fetchedAtMs < REFRESH_MS) {
                    trace.getActiveSpan()?.setAttributes({
                        'logs.retention.cache_hit': true,
                        'logs.retention.rule_count': existing.compiled.rules.length,
                        'logs.retention.version_watermark': existing.versionWatermark,
                    })
                    return existing.compiled
                }
                let rows: RetentionRuleRow[]
                try {
                    rows = await this.fetchRules(teamId)
                } catch (error) {
                    // Fail open: this runs in the ingestion hot path, so a rules-fetch failure
                    // (e.g. a Postgres blip) must never propagate and DLQ otherwise-valid logs.
                    // Serve the last-known compiled rules when we have them; otherwise fall back to
                    // no rules so the caller applies the team default via the batch `retention-days`
                    // header. The stale `fetchedAtMs` means the next message retries the fetch.
                    logger.warn('[logs-retention] rules fetch failed — falling back', {
                        teamId,
                        error: String(error),
                    })
                    trace.getActiveSpan()?.setAttributes({
                        'logs.retention.fetch_failed': true,
                        'logs.retention.served_stale': Boolean(existing),
                    })
                    return existing?.compiled ?? compileRetentionRuleSet([])
                }
                const compiled = compileRetentionRuleSet(rows)
                const vw = rows.reduce((m, r) => Math.max(m, r.version ?? 0), 0)
                this.cache.set(teamId, { compiled, versionWatermark: vw, fetchedAtMs: now })
                trace.getActiveSpan()?.setAttributes({
                    'logs.retention.cache_hit': false,
                    'logs.retention.db_row_count': rows.length,
                    'logs.retention.rule_count': compiled.rules.length,
                    'logs.retention.version_watermark': vw,
                })
                return compiled
            }
        )
    }

    private async fetchRules(teamId: number): Promise<RetentionRuleRow[]> {
        const res = await this.postgres.query<{
            id: string
            config: Record<string, unknown>
            version: string
        }>(
            PostgresUse.COMMON_READ,
            `SELECT id::text AS id, config, version
             FROM logs_logsretentionrule
             WHERE team_id = $1 AND enabled = true
             ORDER BY priority ASC, created_at ASC
             LIMIT ${MAX_ENABLED_RETENTION_RULES}`,
            [teamId],
            'logs-retention-rules-fetch'
        )
        return res.rows.map((r) => ({
            id: r.id,
            config: r.config ?? {},
            version: parseInt(r.version, 10) || 0,
        }))
    }
}
