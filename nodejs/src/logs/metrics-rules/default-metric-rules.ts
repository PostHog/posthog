import {
    type CompiledMetricRule,
    type MetricRuleRow,
    type MetricRuleSource,
    compileMetricRules,
} from './compile-metric-rules'
import { SPAN_VALUE_DURATION_MS } from './tally'

const SPAN_KIND_INTERNAL = '1'

/** Built-in rules, not stored rows: the consumer adds them for teams in the default-rules allowlist. */
const DEFAULT_METRIC_RULE_ROWS: MetricRuleRow[] = [
    {
        // INTERNAL spans are the most numerous, and their names are the most likely to carry ids.
        id: 'default:spans:duration',
        metric_name: 'posthog.span.duration',
        source: 'spans',
        filter_group: {
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [{ key: 'kind', operator: 'is_not', value: SPAN_KIND_INTERNAL, type: 'span_attribute' }],
                },
            ],
        },
        value_attribute: SPAN_VALUE_DURATION_MS,
        group_by: ['service_name', 'kind', 'name', 'status_code'],
    },
    {
        id: 'default:logs:records',
        metric_name: 'posthog.log.records',
        source: 'logs',
        filter_group: null,
        value_attribute: null,
        group_by: ['service_name', 'severity_text'],
    },
]

const compiledDefaults = compileMetricRules(DEFAULT_METRIC_RULE_ROWS)

export const DEFAULT_METRIC_RULES: Record<MetricRuleSource, CompiledMetricRule[]> = {
    logs: compiledDefaults.filter((rule) => rule.source === 'logs'),
    spans: compiledDefaults.filter((rule) => rule.source === 'spans'),
}

/** Appends the source's default rules; a team rule with the same metric name replaces the default. */
export function withDefaultMetricRules(
    teamRules: CompiledMetricRule[],
    source: MetricRuleSource
): CompiledMetricRule[] {
    const teamMetricNames = new Set(teamRules.map((rule) => rule.metricName))
    return [...teamRules, ...DEFAULT_METRIC_RULES[source].filter((rule) => !teamMetricNames.has(rule.metricName))]
}
