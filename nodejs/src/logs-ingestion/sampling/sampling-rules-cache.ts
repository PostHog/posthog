import { trace } from '@opentelemetry/api'
import { Counter } from 'prom-client'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'
import { logger } from '~/utils/logger'

import { type SamplingRuleRow, compileRuleSet } from './compile-rules'
import type { CompiledRuleSet } from './evaluate'

const REFRESH_MS = 30_000

// Hard ceiling on a single rule fetch. A read replica that is unreachable or slow
// (e.g. DATABASE_READONLY_URL pointing at a host that no longer resolves) must never
// block log ingestion — the fetch is bounded and fails open past this.
const FETCH_TIMEOUT_MS = 5_000

const EMPTY_RULE_SET: CompiledRuleSet = { rules: [], hasRateLimitRules: false }

const samplingCacheInstrumentOpts = { measureTime: false, sendException: false } as const

/**
 * Incremented when a rule fetch throws or times out. The cache then fails open — serving
 * the last-good ruleset, or passthrough (empty) when there is none — so a Postgres
 * read-replica outage can never DLQ or stall log ingestion. Mirrors the fail-open
 * posture of the per-record evaluator and the Redis rate limiter.
 */
export const samplingRuleFetchErrorCounter = new Counter({
    name: 'logs_ingestion_sampling_rule_fetch_error_total',
    help: 'Rule fetch from Postgres threw or timed out; cache failed open (served stale or passthrough).',
    labelNames: ['team_id', 'served'],
})

type CacheEntry = {
    compiled: CompiledRuleSet
    versionWatermark: number
    fetchedAtMs: number
}

export class SamplingRulesCache {
    private cache = new Map<number, CacheEntry>()

    constructor(private postgres: PostgresRouter) {}

    public async getCompiledRuleSet(teamId: number): Promise<CompiledRuleSet> {
        return instrumentFn(
            {
                key: 'logsIngestion.sampling.getCompiledRuleSet',
                ...samplingCacheInstrumentOpts,
                getLoggingContext: () => ({ team_id: teamId }),
            },
            async () => {
                const now = Date.now()
                const existing = this.cache.get(teamId)
                if (existing && now - existing.fetchedAtMs < REFRESH_MS) {
                    trace.getActiveSpan()?.setAttributes({
                        'logs.sampling.cache_hit': true,
                        'logs.sampling.rule_count': existing.compiled.rules.length,
                        'logs.sampling.version_watermark': existing.versionWatermark,
                    })
                    return existing.compiled
                }
                try {
                    const rows = await this.fetchRulesWithTimeout(teamId)
                    const compiled = compileRuleSet(rows)
                    const vw = rows.reduce((m, r) => Math.max(m, r.version ?? 0), 0)
                    this.cache.set(teamId, { compiled, versionWatermark: vw, fetchedAtMs: now })
                    trace.getActiveSpan()?.setAttributes({
                        'logs.sampling.cache_hit': false,
                        'logs.sampling.db_row_count': rows.length,
                        'logs.sampling.rule_count': compiled.rules.length,
                        'logs.sampling.version_watermark': vw,
                    })
                    return compiled
                } catch (err) {
                    // Fail open. A throwing or hanging read replica must not block or DLQ log
                    // ingestion — serve the last-good ruleset if we have one, else passthrough
                    // (empty). Stamp `fetchedAtMs` so we back off to one retry per REFRESH_MS
                    // instead of re-hitting the failing query on every message.
                    const served = existing ? 'stale' : 'empty'
                    const fallback = existing?.compiled ?? EMPTY_RULE_SET
                    this.cache.set(teamId, {
                        compiled: fallback,
                        versionWatermark: existing?.versionWatermark ?? 0,
                        fetchedAtMs: now,
                    })
                    samplingRuleFetchErrorCounter.inc({ team_id: String(teamId), served })
                    logger.warn('[logs-sampling] rule fetch failed — failing open', {
                        teamId,
                        served,
                        error: err instanceof Error ? err.message : String(err),
                    })
                    trace.getActiveSpan()?.setAttributes({
                        'logs.sampling.cache_hit': false,
                        'logs.sampling.fetch_error': true,
                        'logs.sampling.fetch_error_served': served,
                        'logs.sampling.rule_count': fallback.rules.length,
                    })
                    return fallback
                }
            }
        )
    }

    /**
     * Bound a rule fetch so a slow or unreachable read replica cannot stall the hot path.
     * On timeout the losing fetch is abandoned (its late rejection is swallowed to avoid an
     * unhandled rejection); the caller treats the timeout as a fetch failure and fails open.
     */
    private async fetchRulesWithTimeout(teamId: number): Promise<SamplingRuleRow[]> {
        const fetchPromise = this.fetchRules(teamId)
        fetchPromise.catch(() => {})
        let timer: ReturnType<typeof setTimeout> | undefined
        const timeout = new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error(`rule fetch exceeded ${FETCH_TIMEOUT_MS}ms`)), FETCH_TIMEOUT_MS)
        })
        try {
            return await Promise.race([fetchPromise, timeout])
        } finally {
            if (timer) {
                clearTimeout(timer)
            }
        }
    }

    private async fetchRules(teamId: number): Promise<SamplingRuleRow[]> {
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
             WHERE team_id = $1 AND enabled = true
             ORDER BY priority ASC, created_at ASC`,
            [teamId],
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
