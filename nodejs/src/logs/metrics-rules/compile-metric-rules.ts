import { parseFilterGroup } from '../sampling/compile-rules'
import type { FilterGroupNode } from '../sampling/filter-group-match'

/** Mirrors `MAX_METRIC_RULE_GROUP_BY_KEYS` in `products/logs/backend/models.py`. */
export const MAX_GROUP_BY_KEYS = 5

/** Raw row shape from `logs_logsmetricrule` (see `MetricRulesCache.fetchRules`). */
export type MetricRuleRow = {
    id: string
    metric_name: string
    filter_group: unknown
    value_attribute: string | null
    group_by: unknown
    /** Row version from DB; used by cache watermark only, ignored by compileMetricRules. */
    version?: number
}

export type CompiledMetricRule = {
    id: string
    metricName: string
    /** null = every ingested log record matches. */
    filterGroup: FilterGroupNode | null
    /** Log attribute key holding the numeric value to aggregate; null = count records. */
    valueAttribute: string | null
    groupBy: string[]
}

export function compileMetricRules(rows: MetricRuleRow[]): CompiledMetricRule[] {
    const out: CompiledMetricRule[] = []
    for (const row of rows) {
        if (typeof row.metric_name !== 'string' || row.metric_name === '') {
            continue
        }
        let filterGroup: FilterGroupNode | null = null
        if (row.filter_group != null) {
            filterGroup = parseFilterGroup(row.filter_group)
            if (!filterGroup) {
                // Unlike drop rules (where an unparseable filter makes the rule inert, which is
                // safe), a metric rule with a null filter means "count everything" — so an
                // unparseable filter must skip the whole rule to fail closed on emission.
                continue
            }
        }
        const groupBy = Array.isArray(row.group_by)
            ? row.group_by.filter((k): k is string => typeof k === 'string' && k !== '').slice(0, MAX_GROUP_BY_KEYS)
            : []
        out.push({
            id: row.id,
            metricName: row.metric_name,
            filterGroup,
            valueAttribute:
                typeof row.value_attribute === 'string' && row.value_attribute !== '' ? row.value_attribute : null,
            groupBy,
        })
    }
    return out
}
