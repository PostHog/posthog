import {
    type CompiledMetricRule,
    type MetricRuleRow,
    type MetricRuleSource,
    compileMetricRules,
} from './compile-metric-rules'
import { SPAN_VALUE_DURATION_MS } from './tally'

/** OTel `SpanKind.INTERNAL` on the span Avro wire. */
const SPAN_KIND_INTERNAL = '1'

/**
 * Built-in rules for a team with no metrics of its own, so its default view has request,
 * error and latency series without any setup. They are not stored rows: the consumer adds
 * them to the team's own rules when the team is in the default-rules allowlist.
 */
const DEFAULT_METRIC_RULE_ROWS: MetricRuleRow[] = [
    {
        // One histogram gives request rate (count), error rate (status_code = ERROR) and
        // latency percentiles per endpoint (SERVER, CONSUMER) and per dependency (CLIENT,
        // PRODUCER). INTERNAL spans are excluded: they are the most numerous and their
        // names are the most likely to carry ids.
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
