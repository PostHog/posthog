import { MetricRecord, unwrap } from './metric-record-avro'

// 15 seconds divides every query interval, so one bucket never spans two query intervals.
export const AGGREGATION_BUCKET_MICROS = 15_000_000n

type AggregationKind = 'delta' | 'cumulative'

// A histogram's `count` is its number of observations, so a merged histogram point cannot record
// how many points it replaces.
function aggregationKind(record: MetricRecord): AggregationKind | null {
    if (unwrap<string>(record.metric_type) !== 'sum') {
        return null
    }
    const value = unwrap<number>(record.value)
    if (
        unwrap<bigint>(record.series_fingerprint) === null ||
        unwrap<bigint>(record.timestamp) === null ||
        unwrap<bigint>(record.count) === null ||
        value === null ||
        !Number.isFinite(value)
    ) {
        return null
    }
    // A sample query filters by trace, so a point linked to a trace keeps its own value.
    if ((unwrap<Buffer>(record.trace_id)?.length ?? 0) > 0) {
        return null
    }
    const temporality = unwrap<string>(record.aggregation_temporality)
    if (temporality === 'delta') {
        return 'delta'
    }
    if (temporality === 'cumulative' && unwrap<boolean>(record.is_monotonic) === true) {
        return 'cumulative'
    }
    return null
}

function groupKey(record: MetricRecord, kind: AggregationKind): string {
    const bucket = unwrap<bigint>(record.timestamp)! / AGGREGATION_BUCKET_MICROS
    // The fingerprint does not cover these fields, and ClickHouse keeps one value of each per stored row.
    return JSON.stringify([
        kind,
        String(unwrap<bigint>(record.series_fingerprint)),
        String(bucket),
        unwrap<boolean>(record.is_monotonic),
        unwrap<string>(record.unit),
        unwrap<number>(record.retention_days),
        record.has_labels ?? null,
    ])
}

const timestampOf = (record: MetricRecord): bigint => unwrap<bigint>(record.timestamp)!
const valueOf = (record: MetricRecord): number => unwrap<number>(record.value)!
const countOf = (record: MetricRecord): bigint => unwrap<bigint>(record.count)!

function withValueAndCount(record: MetricRecord, value: number, count: bigint): MetricRecord {
    return { ...record, value: { double: value }, count: { long: count } }
}

function sortByTimestamp(records: MetricRecord[]): MetricRecord[] {
    return [...records].sort((a, b) => {
        const diff = timestampOf(a) - timestampOf(b)
        return diff === 0n ? 0 : diff < 0n ? -1 : 1
    })
}

function aggregateDelta(records: MetricRecord[]): MetricRecord[] {
    const sorted = sortByTimestamp(records)
    let value = 0
    let count = 0n
    for (const record of sorted) {
        value += valueOf(record)
        count += countOf(record)
    }
    return [withValueAndCount(sorted[sorted.length - 1], value, count)]
}

// The first point keeps a reset between two groups visible to the query. The points on both sides of
// each drop in value keep the reset visible when the value climbs past its old level in one group.
function aggregateCumulative(records: MetricRecord[]): MetricRecord[] {
    const sorted = sortByTimestamp(records)
    const last = sorted.length - 1
    const kept: MetricRecord[] = []
    let count = 0n
    for (let index = 0; index <= last; index++) {
        const record = sorted[index]
        count += countOf(record)
        const beforeReset = index < last && valueOf(sorted[index + 1]) < valueOf(record)
        const afterReset = index > 0 && valueOf(record) < valueOf(sorted[index - 1])
        if (index === 0 || index === last || beforeReset || afterReset) {
            kept.push(withValueAndCount(record, valueOf(record), count))
            count = 0n
        }
    }
    return kept
}

export function aggregateMetricRecords(records: MetricRecord[]): MetricRecord[] {
    const output: MetricRecord[] = []
    const groups = new Map<string, { kind: AggregationKind; records: MetricRecord[] }>()
    for (const record of records) {
        const kind = aggregationKind(record)
        if (kind === null) {
            output.push(record)
            continue
        }
        const key = groupKey(record, kind)
        const group = groups.get(key)
        if (group) {
            group.records.push(record)
        } else {
            groups.set(key, { kind, records: [record] })
        }
    }
    for (const group of groups.values()) {
        output.push(...(group.kind === 'delta' ? aggregateDelta(group.records) : aggregateCumulative(group.records)))
    }
    return output
}

export function isAggregatable(record: MetricRecord): boolean {
    return aggregationKind(record) !== null
}
