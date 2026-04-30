import { PostgresRouter, PostgresUse } from '~/utils/db/postgres'

import { type SamplingRuleRow, compileRuleSet } from './compile-rules'
import type { CompiledRuleSet } from './evaluate'

const REFRESH_MS = 30_000

type CacheEntry = {
    compiled: CompiledRuleSet
    versionWatermark: number
    fetchedAtMs: number
}

export class SamplingRulesCache {
    private cache = new Map<number, CacheEntry>()

    constructor(private postgres: PostgresRouter) {}

    public async getCompiledRuleSet(teamId: number): Promise<CompiledRuleSet> {
        const now = Date.now()
        const existing = this.cache.get(teamId)
        if (existing && now - existing.fetchedAtMs < REFRESH_MS) {
            return existing.compiled
        }
        const rows = await this.fetchRules(teamId)
        const compiled = compileRuleSet(rows)
        const vw = rows.reduce((m, r) => Math.max(m, r.version ?? 0), 0)
        this.cache.set(teamId, { compiled, versionWatermark: vw, fetchedAtMs: now })
        return compiled
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
