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
    // Without a start time, a reset is visible only in the whole timeline, which one batch never sees.
    if (
        temporality === 'cumulative' &&
        unwrap<boolean>(record.is_monotonic) === true &&
        unwrap<bigint>(record.start_timestamp) !== null
    ) {
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
        // Each delta point has its own start time, so only a cumulative point groups by it.
        kind === 'cumulative' ? String(unwrap<bigint>(record.start_timestamp)) : null,
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

// A cumulative value only rises within one start time, so the first and last points of each slice
// keep every increase, and the points at each reset survive in whichever slice holds them.
function aggregateCumulative(records: MetricRecord[]): MetricRecord[] {
    const sorted = sortByTimestamp(records)
    const first = sorted[0]
    const last = sorted[sorted.length - 1]
    if (sorted.length === 1) {
        return [first]
    }
    const restCount = sorted.slice(1).reduce((total, record) => total + countOf(record), 0n)
    return [first, withValueAndCount(last, valueOf(last), restCount)]
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
