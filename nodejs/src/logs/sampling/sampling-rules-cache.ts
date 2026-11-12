import { trace } from '@opentelemetry/api'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import { type SamplingRuleRow, compileRuleSet } from './compile-rules'
import type { CompiledRuleSet } from './evaluate'

const REFRESH_MS = 30_000
// After a failed fetch, wait this long before the next try, so an outage does not get one query per message.
const FAILED_FETCH_RETRY_MS = 5_000

/** Record source a drop rule filters. Mirrors `LogsExclusionRule.RecordSource` in models.py. */
export type SamplingRuleSource = 'logs' | 'spans'

const samplingCacheInstrumentOpts = { measureTime: false, sendException: false } as const

type CacheEntry = {
    compiled: CompiledRuleSet
    versionWatermark: number
    fetchedAtMs: number
}

export class SamplingRulesCache {
    // Keyed by team *and* source: a team can have both log and span rules, and each consumer
    // must only see its own.
    private cache = new Map<string, CacheEntry>()

    constructor(private postgres: PostgresRouter) {}

    public async getCompiledRuleSet(teamId: number, source: SamplingRuleSource = 'logs'): Promise<CompiledRuleSet> {
        return instrumentFn(
            {
                key: 'logsIngestion.sampling.getCompiledRuleSet',
                ...samplingCacheInstrumentOpts,
                getLoggingContext: () => ({ team_id: teamId, source }),
            },
            async () => {
                const now = Date.now()
                const cacheKey = `${teamId}:${source}`
                const existing = this.cache.get(cacheKey)
                if (existing && now - existing.fetchedAtMs < REFRESH_MS) {
                    trace.getActiveSpan()?.setAttributes({
                        'logs.sampling.cache_hit': true,
                        'logs.sampling.rule_count': existing.compiled.rules.length,
                        'logs.sampling.version_watermark': existing.versionWatermark,
                    })
                    return existing.compiled
                }
                let rows: SamplingRuleRow[]
                try {
                    rows = await this.fetchRules(teamId, source)
                } catch (error) {
                    // Fail open: a rules-fetch failure in the hot path must not DLQ valid records.
                    // Serve the last-known rules, or no rules, so nothing is dropped by mistake.
                    logger.warn('[logs-sampling] rules fetch failed — falling back', {
                        teamId,
                        source,
                        error: String(error),
                    })
                    trace.getActiveSpan()?.setAttributes({
                        'logs.sampling.fetch_failed': true,
                        'logs.sampling.served_stale': Boolean(existing),
                    })
                    const fallback = existing?.compiled ?? compileRuleSet([])
                    this.cache.set(cacheKey, {
                        compiled: fallback,
                        versionWatermark: existing?.versionWatermark ?? 0,
                        fetchedAtMs: now - REFRESH_MS + FAILED_FETCH_RETRY_MS,
                    })
                    return fallback
                }
                // The API rejects severity rules for spans. A span has no severity, so a row written
                // past the API would rank every span as info and apply one action to all of them.
                const applicable = source === 'spans' ? rows.filter((r) => r.rule_type !== 'severity_sampling') : rows
                const compiled = compileRuleSet(applicable)
                const vw = rows.reduce((m, r) => Math.max(m, r.version ?? 0), 0)
                this.cache.set(cacheKey, { compiled, versionWatermark: vw, fetchedAtMs: now })
                trace.getActiveSpan()?.setAttributes({
                    'logs.sampling.cache_hit': false,
                    'logs.sampling.db_row_count': rows.length,
                    'logs.sampling.rule_count': compiled.rules.length,
                    'logs.sampling.version_watermark': vw,
                })
                return compiled
            }
        )
    }

    private async fetchRules(teamId: number, source: SamplingRuleSource): Promise<SamplingRuleRow[]> {
        const res = await this.postgres.query<{
            id: string
            rule_type: string
            scope_service: string | null
            scope_path_pattern: string | null
            scope_attribute_filters: unknown
            config: Record<string, unknown>
            version: string
        }>(
            PostgresUse.COMMON_READ,
            `SELECT id::text AS id, rule_type, scope_service, scope_path_pattern,
                    scope_attribute_filters, config, version
             FROM logs_logsexclusionrule
             WHERE team_id = $1 AND enabled = true AND source = $2
             ORDER BY priority ASC, created_at ASC`,
            [teamId, source],
            'logs-exclusion-rules-fetch'
        )
        return res.rows.map((r) => ({
            id: r.id,
            rule_type: r.rule_type,
            scope_service: r.scope_service,
            scope_path_pattern: r.scope_path_pattern,
            scope_attribute_filters: r.scope_attribute_filters,
            config: r.config ?? {},
            version: parseInt(r.version, 10) || 0,
        }))
    }
}
