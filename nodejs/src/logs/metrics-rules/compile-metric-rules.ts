import { parseFilterGroup } from '../sampling/compile-rules'
import type { FilterGroupNode } from '../sampling/filter-group-match'

/** Mirrors `MAX_METRIC_RULE_GROUP_BY_KEYS` in `products/logs/backend/models.py`. */
export const MAX_GROUP_BY_KEYS = 5

/** Record source a rule tallies. Mirrors `LogsMetricRule.RecordSource` in models.py. */
export type MetricRuleSource = 'logs' | 'spans'

/** Top-level keys usable as span group-by dimensions (log-only keys like severity_text excluded). */
export const SPAN_GROUP_BY_TOP_LEVEL_KEYS = new Set(['service_name', 'name', 'status_code'])

/** Raw row shape from `logs_logsmetricrule` (see `MetricRulesCache.fetchRules`). */
export type MetricRuleRow = {
    id: string
    metric_name: string
    filter_group: unknown
    value_attribute: string | null
    group_by: unknown
    /** Record source; absent rows are log rules (pre-source schema default). */
    source?: string
    /** Row version from DB; used by cache watermark only, ignored by compileMetricRules. */
    version?: number
}

export type CompiledMetricRule = {
    id: string
    metricName: string
    source: MetricRuleSource
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
        const source: MetricRuleSource = row.source === 'spans' ? 'spans' : 'logs'
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
        if (source === 'spans') {
            // Fail closed: a span rule carrying a log-only top-level key would silently emit
            // empty-label series, so drop the rule instead of tallying garbage.
            const hasLogOnlyKey = groupBy.some(
                (k) =>
                    !SPAN_GROUP_BY_TOP_LEVEL_KEYS.has(k) &&
                    !k.startsWith('attributes.') &&
                    !k.startsWith('resource_attributes.')
            )
            if (hasLogOnlyKey) {
                continue
            }
        }
        out.push({
            id: row.id,
            metricName: row.metric_name,
            source,
            filterGroup,
            valueAttribute:
                typeof row.value_attribute === 'string' && row.value_attribute !== '' ? row.value_attribute : null,
            groupBy,
        })
    }
    return out
}
