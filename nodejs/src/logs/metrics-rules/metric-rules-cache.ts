import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'

import { type CompiledMetricRule, type MetricRuleRow, compileMetricRules } from './compile-metric-rules'

const REFRESH_MS = 30_000

type CacheEntry = {
    compiled: CompiledMetricRule[]
    fetchedAtMs: number
}

/** Per-team compiled metric rules with a 30s TTL, mirroring `SamplingRulesCache`. */
export class MetricRulesCache {
    private cache = new Map<number, CacheEntry>()

    constructor(private postgres: PostgresRouter) {}

    public async getCompiledRules(teamId: number): Promise<CompiledMetricRule[]> {
        const now = Date.now()
        const existing = this.cache.get(teamId)
        if (existing && now - existing.fetchedAtMs < REFRESH_MS) {
            return existing.compiled
        }
        const rows = await this.fetchRules(teamId)
        const compiled = compileMetricRules(rows)
        this.cache.set(teamId, { compiled, fetchedAtMs: now })
        return compiled
    }

    private async fetchRules(teamId: number): Promise<MetricRuleRow[]> {
        const res = await this.postgres.query<{
            id: string
            metric_name: string
            filter_group: unknown
            value_attribute: string | null
            group_by: unknown
        }>(
            PostgresUse.COMMON_READ,
            `SELECT id::text AS id, metric_name, filter_group, value_attribute, group_by
             FROM logs_logsmetricrule
             WHERE team_id = $1 AND enabled = true
             ORDER BY created_at ASC`,
            [teamId],
            'logs-metric-rules-fetch'
        )
        return res.rows
    }
}
