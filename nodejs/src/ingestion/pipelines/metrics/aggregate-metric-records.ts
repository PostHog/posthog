import { MetricRecord, unwrap } from './metric-record-avro'

// 15 seconds divides every query interval, so one bucket never spans two query intervals.
export const AGGREGATION_BUCKET_MICROS = 15_000_000n

type AggregationKind = 'delta' | 'cumulative' | 'delta_histogram'

const HISTOGRAM_TYPES = new Set(['histogram', 'exponential_histogram'])

const boundsOf = (record: MetricRecord): number[] => unwrap<number[]>(record.histogram_bounds) ?? []
const bucketCountsOf = (record: MetricRecord): bigint[] => unwrap<bigint[]>(record.histogram_counts) ?? []

function hasCommonFields(record: MetricRecord): boolean {
    const value = unwrap<number>(record.value)
    return (
        unwrap<bigint>(record.series_fingerprint) !== null &&
        unwrap<bigint>(record.timestamp) !== null &&
        unwrap<bigint>(record.count) !== null &&
        value !== null &&
        Number.isFinite(value) &&
        // A sample query filters by trace, so a point linked to a trace keeps its own value.
        (unwrap<Buffer>(record.trace_id)?.length ?? 0) === 0
    )
}

// A histogram's `count` is its number of observations, so merged histogram points add their counts
// and buckets. Only points with the same bucket bounds merge, and a bound that JSON cannot hold
// (NaN, Infinity) would make two different layouts share a group key.
function histogramKind(record: MetricRecord): AggregationKind | null {
    if (unwrap<string>(record.aggregation_temporality) !== 'delta') {
        return null
    }
    const bounds = unwrap<number[]>(record.histogram_bounds)
    const bucketCounts = unwrap<bigint[]>(record.histogram_counts)
    if (bounds === null || bucketCounts === null || !bounds.every(Number.isFinite)) {
        return null
    }
    return 'delta_histogram'
}

function aggregationKind(record: MetricRecord): AggregationKind | null {
    const metricType = unwrap<string>(record.metric_type)
    if (metricType === null || !hasCommonFields(record)) {
        return null
    }
    if (HISTOGRAM_TYPES.has(metricType)) {
        return histogramKind(record)
    }
    if (metricType !== 'sum') {
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
        kind === 'delta_histogram' ? boundsOf(record) : null,
        kind === 'delta_histogram' ? bucketCountsOf(record).length : null,
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

function aggregateDeltaHistogram(records: MetricRecord[]): MetricRecord[] {
    const sorted = sortByTimestamp(records)
    let sum = 0
    let count = 0n
    const bucketCounts = bucketCountsOf(sorted[0]).map(() => 0n)
    for (const record of sorted) {
        sum += valueOf(record)
        count += countOf(record)
        bucketCountsOf(record).forEach((bucketCount, bucket) => {
            bucketCounts[bucket] += bucketCount
        })
    }
    const latest = sorted[sorted.length - 1]
    return [{ ...withValueAndCount(latest, sum, count), histogram_counts: { array: bucketCounts } }]
}

// A value only rises within one start time, so first and last points keep the increase. The counter
// query reads the second point to decide whether a series' first point counts from zero.
function aggregateCumulative(records: MetricRecord[]): MetricRecord[] {
    const sorted = sortByTimestamp(records)
    if (sorted.length <= 3) {
        return sorted
    }
    const last = sorted[sorted.length - 1]
    const restCount = sorted.slice(2).reduce((total, record) => total + countOf(record), 0n)
    return [sorted[0], sorted[1], withValueAndCount(last, valueOf(last), restCount)]
}

const AGGREGATORS: Record<AggregationKind, (records: MetricRecord[]) => MetricRecord[]> = {
    delta: aggregateDelta,
    cumulative: aggregateCumulative,
    delta_histogram: aggregateDeltaHistogram,
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
        output.push(...AGGREGATORS[group.kind](group.records))
    }
    return output
}

export function isAggregatable(record: MetricRecord): boolean {
    return aggregationKind(record) !== null
}
