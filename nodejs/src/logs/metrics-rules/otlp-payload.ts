import type { CompiledMetricRule } from './compile-metric-rules'
import type { BatchTallies, MetricTallyEntry } from './tally'

/**
 * Hand-built OTLP/JSON `ExportMetricsServiceRequest` for log-generated metrics.
 *
 * Wire shape follows what capture-logs parses (same conventions as
 * `~/common/metrics/otlp-json-exporter.ts`): camelCase fields, unix nanos as decimal
 * strings, proto enum value 1 for delta temporality, hex trace/span ids on exemplars.
 * The OTel SDK is not usable here — its meter provider is per-process with a single
 * resource and token, while these payloads are per-team with per-rule label sets.
 */

const SCOPE = { name: 'posthog/logs-metric-rules' }

/** Data points are stamped on 10-second boundaries, matching Datadog's log-based metric granularity. */
const TIME_BUCKET_MS = 10_000

const OTLP_TEMPORALITY_DELTA = 1

const ATTRIBUTE_PREFIXES = ['attributes.', 'resource_attributes.']

/** Label name as it appears on the emitted series: map keys lose their prefix (Datadog drops `@` the same way). */
function labelName(groupByKey: string): string {
    for (const prefix of ATTRIBUTE_PREFIXES) {
        if (groupByKey.startsWith(prefix)) {
            return groupByKey.slice(prefix.length)
        }
    }
    return groupByKey
}

function snapToBucketNanos(nowMs: number): bigint {
    return BigInt(Math.floor(nowMs / TIME_BUCKET_MS) * TIME_BUCKET_MS) * 1_000_000n
}

type RulePoints = { rule: CompiledMetricRule; entries: MetricTallyEntry[] }

export function buildMetricRulesOtlpPayload(
    rules: CompiledMetricRule[],
    tallies: BatchTallies,
    nowMs: number
): Record<string, unknown> | null {
    // Partition label sets by service value: `service_name` group-bys become the OTel
    // resource `service.name` (one resource block per service), so the emitted series
    // carries service identity in the same place every other metric producer puts it —
    // first-class `service_name` column, resource-scoped filters, stable fingerprints.
    const byService = new Map<string, Map<string, RulePoints>>()
    for (const rule of rules) {
        const ruleTallies = tallies.byRule.get(rule.id)
        if (!ruleTallies?.size) {
            continue
        }
        const serviceIndex = rule.groupBy.indexOf('service_name')
        for (const entry of ruleTallies.values()) {
            const service = serviceIndex >= 0 ? (entry.labelValues[serviceIndex] ?? '') : ''
            let ruleMap = byService.get(service)
            if (!ruleMap) {
                ruleMap = new Map()
                byService.set(service, ruleMap)
            }
            let points = ruleMap.get(rule.id)
            if (!points) {
                points = { rule, entries: [] }
                ruleMap.set(rule.id, points)
            }
            points.entries.push(entry)
        }
    }
    if (byService.size === 0) {
        return null
    }

    const timeNanos = snapToBucketNanos(nowMs)
    const timeUnixNano = timeNanos.toString()
    const startTimeUnixNano = (timeNanos - BigInt(TIME_BUCKET_MS) * 1_000_000n).toString()

    const resourceMetrics = [...byService.entries()].map(([service, ruleMap]) => ({
        resource: {
            attributes: service === '' ? [] : [{ key: 'service.name', value: { stringValue: service } }],
        },
        scopeMetrics: [
            {
                scope: SCOPE,
                metrics: [...ruleMap.values()].map(({ rule, entries }) =>
                    serializeRuleMetric(rule, entries, startTimeUnixNano, timeUnixNano)
                ),
            },
        ],
    }))

    return { resourceMetrics }
}

function serializeRuleMetric(
    rule: CompiledMetricRule,
    entries: MetricTallyEntry[],
    startTimeUnixNano: string,
    timeUnixNano: string
): Record<string, unknown> {
    if (rule.valueAttribute) {
        return {
            name: rule.metricName,
            histogram: {
                dataPoints: entries.map((entry) => ({
                    ...dataPointBase(rule, entry, startTimeUnixNano, timeUnixNano),
                    count: entry.count,
                    sum: entry.sum,
                    // No percentile buckets yet: a single catch-all bucket keeps the shape a
                    // valid OTLP histogram while carrying only count + sum.
                    bucketCounts: [entry.count],
                    explicitBounds: [],
                })),
                aggregationTemporality: OTLP_TEMPORALITY_DELTA,
            },
        }
    }
    return {
        name: rule.metricName,
        sum: {
            dataPoints: entries.map((entry) => ({
                ...dataPointBase(rule, entry, startTimeUnixNano, timeUnixNano),
                asDouble: entry.count,
            })),
            aggregationTemporality: OTLP_TEMPORALITY_DELTA,
            isMonotonic: true,
        },
    }
}

function dataPointBase(
    rule: CompiledMetricRule,
    entry: MetricTallyEntry,
    startTimeUnixNano: string,
    timeUnixNano: string
): Record<string, unknown> {
    const attributes: Record<string, unknown>[] = []
    for (let i = 0; i < rule.groupBy.length; i++) {
        const key = rule.groupBy[i]!
        if (key === 'service_name') {
            continue // carried on the resource block instead
        }
        attributes.push({ key: labelName(key), value: { stringValue: entry.labelValues[i] ?? '' } })
    }
    return {
        attributes,
        startTimeUnixNano,
        timeUnixNano,
        ...(entry.exemplarTraceId
            ? {
                  exemplars: [
                      {
                          filteredAttributes: [],
                          timeUnixNano,
                          asDouble: rule.valueAttribute ? entry.sum : entry.count,
                          traceId: entry.exemplarTraceId,
                          ...(entry.exemplarSpanId ? { spanId: entry.exemplarSpanId } : {}),
                      },
                  ],
              }
            : {}),
    }
}
