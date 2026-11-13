import avro from 'avsc'

import { AGGREGATION_BUCKET_MICROS, aggregateMetricRecords } from './aggregate-metric-records'
import { MetricRecord, parseWriterSchema, unwrap } from './metric-record-avro'

type Point = {
    type?: string
    temporality?: string
    monotonic?: boolean
    fingerprint?: bigint
    traced?: boolean
    start?: bigint | null
    ts: bigint
    value: number
}

const BASE_TS = 1_700_000_010_000_000n - (1_700_000_010_000_000n % AGGREGATION_BUCKET_MICROS)

const record = ({
    type = 'sum',
    temporality = 'delta',
    monotonic = true,
    fingerprint = 1n,
    traced = false,
    start = 1n,
    ts,
    value,
}: Point) => ({
    metric_type: { string: type },
    aggregation_temporality: { string: temporality },
    is_monotonic: { boolean: monotonic },
    series_fingerprint: { long: fingerprint },
    timestamp: { long: BASE_TS + ts },
    start_timestamp: start === null ? null : { long: start },
    value: { double: value },
    count: { long: 1n },
    trace_id: traced ? { bytes: Buffer.from('trace') } : null,
    unit: { string: '' },
    retention_days: null,
    has_labels: true,
})

type Summary = [string, bigint, number, bigint, boolean]

const bySeriesTimeValue = (a: Summary, b: Summary): number =>
    a[0].localeCompare(b[0]) || Number(a[1] - b[1]) || a[2] - b[2]

const summarize = (records: MetricRecord[]): Summary[] =>
    records
        .map(
            (r): Summary => [
                String(unwrap(r.series_fingerprint)),
                unwrap<bigint>(r.timestamp)! - BASE_TS,
                unwrap<number>(r.value)!,
                unwrap<bigint>(r.count)!,
                r.trace_id !== null,
            ]
        )
        .sort(bySeriesTimeValue)

describe('aggregateMetricRecords', () => {
    const NEXT_BUCKET = AGGREGATION_BUCKET_MICROS

    it.each<[string, Point[], Summary[]]>([
        [
            'sums untraced delta points per series and bucket, keeping the latest timestamp and the point count',
            [
                { ts: 3n, value: 10 },
                { ts: 1n, value: 10 },
                { ts: 2n, value: 5 },
                { fingerprint: 2n, ts: 1n, value: 7 },
                { ts: NEXT_BUCKET, value: 1 },
                { traced: true, ts: 2n, value: 4 },
            ],
            [
                ['1', 2n, 4, 1n, true],
                ['1', 3n, 25, 3n, false],
                ['1', NEXT_BUCKET, 1, 1n, false],
                ['2', 1n, 7, 1n, false],
            ],
        ],
        [
            'keeps the first two and the last cumulative points of each start time',
            [
                { temporality: 'cumulative', start: 1n, ts: 1n, value: 100 },
                { temporality: 'cumulative', start: 1n, ts: 2n, value: 101 },
                { temporality: 'cumulative', start: 1n, ts: 3n, value: 400 },
                { temporality: 'cumulative', start: 1n, ts: 4n, value: 900 },
                { temporality: 'cumulative', start: 2n, ts: 5n, value: 5 },
                { temporality: 'cumulative', start: 2n, ts: 6n, value: 1000 },
                { temporality: 'cumulative', start: 2n, ts: 7n, value: 1200 },
                { temporality: 'cumulative', start: 2n, ts: 8n, value: 1300 },
            ],
            [
                ['1', 1n, 100, 1n, false],
                ['1', 2n, 101, 1n, false],
                ['1', 4n, 900, 2n, false],
                ['1', 5n, 5, 1n, false],
                ['1', 6n, 1000, 1n, false],
                ['1', 8n, 1300, 2n, false],
            ],
        ],
        [
            'passes through gauges, cumulative histograms, non-monotonic cumulative sums and cumulative sums without a start time',
            [
                { type: 'gauge', ts: 1n, value: 1 },
                { type: 'gauge', ts: 2n, value: 2 },
                { type: 'histogram', temporality: 'cumulative', ts: 1n, value: 3 },
                { type: 'histogram', temporality: 'cumulative', ts: 2n, value: 4 },
                { temporality: 'cumulative', monotonic: false, ts: 1n, value: 9 },
                { temporality: 'cumulative', monotonic: false, ts: 2n, value: 8 },
                { temporality: 'cumulative', start: null, fingerprint: 2n, ts: 1n, value: 50 },
                { temporality: 'cumulative', start: null, fingerprint: 2n, ts: 2n, value: 60 },
                { temporality: 'cumulative', start: null, fingerprint: 2n, ts: 3n, value: 70 },
            ],
            [
                ['1', 1n, 1, 1n, false],
                ['1', 1n, 3, 1n, false],
                ['1', 1n, 9, 1n, false],
                ['1', 2n, 2, 1n, false],
                ['1', 2n, 4, 1n, false],
                ['1', 2n, 8, 1n, false],
                ['2', 1n, 50, 1n, false],
                ['2', 2n, 60, 1n, false],
                ['2', 3n, 70, 1n, false],
            ],
        ],
    ])('%s', (_name, points, expected) => {
        expect(summarize(aggregateMetricRecords(points.map(record)))).toEqual(expected.sort(bySeriesTimeValue))
    })

    it('keeps the increase exact when one cumulative series is split across slices', () => {
        const points: Point[] = [
            { temporality: 'cumulative', start: 1n, ts: 1n, value: 100 },
            { temporality: 'cumulative', start: 1n, ts: 2n, value: 800 },
            { temporality: 'cumulative', start: 1n, ts: 3n, value: 900 },
            { temporality: 'cumulative', start: 2n, ts: 4n, value: 5 },
            { temporality: 'cumulative', start: 2n, ts: 5n, value: 1000 },
        ]
        const sliceA = aggregateMetricRecords(points.filter((_, i) => i % 2 === 0).map(record))
        const sliceB = aggregateMetricRecords(points.filter((_, i) => i % 2 === 1).map(record))
        const values = summarize([...sliceA, ...sliceB]).map(([, , value]) => value)

        // The query treats a drop in value as a reset from 0, as `_build_counter_query` does.
        const increase = values
            .slice(1)
            .reduce((total, value, i) => total + (value >= values[i] ? value - values[i] : value), 0)
        expect(increase).toEqual(1800)
    })

    type HistogramPoint = {
        type?: string
        temporality?: string
        traced?: boolean
        ts: bigint
        bounds?: number[]
        buckets: bigint[]
        sum: number
    }

    const histogram = ({
        type = 'histogram',
        temporality = 'delta',
        traced = false,
        ts,
        bounds = [1, 5],
        buckets,
        sum,
    }: HistogramPoint): MetricRecord => ({
        ...record({ type, temporality, monotonic: false, traced, ts, value: sum }),
        count: { long: buckets.reduce((total, bucket) => total + bucket, 0n) },
        histogram_bounds: { array: bounds },
        histogram_counts: { array: buckets },
    })

    type HistogramSummary = [bigint, number[], bigint[], number, bigint, boolean]

    const summarizeHistograms = (records: MetricRecord[]): HistogramSummary[] =>
        records
            .map(
                (r): HistogramSummary => [
                    unwrap<bigint>(r.timestamp)! - BASE_TS,
                    unwrap<number[]>(r.histogram_bounds)!,
                    unwrap<bigint[]>(r.histogram_counts)!,
                    unwrap<number>(r.value)!,
                    unwrap<bigint>(r.count)!,
                    r.trace_id !== null,
                ]
            )
            .sort((a, b) => Number(a[0] - b[0]) || a[3] - b[3])

    it.each<[string, HistogramPoint[], HistogramSummary[]]>([
        [
            'adds the buckets, sums and counts of delta histograms with the same bounds, keeping the latest timestamp',
            [
                { ts: 2n, buckets: [1n, 0n, 2n], sum: 12 },
                { ts: 1n, buckets: [0n, 3n, 0n], sum: 9 },
                { ts: 3n, buckets: [0n, 0n, 0n], sum: 0 },
                { type: 'exponential_histogram', ts: 1n, bounds: [1, 2], buckets: [1n, 1n], sum: 3 },
                { type: 'exponential_histogram', ts: 2n, bounds: [1, 2], buckets: [2n, 0n], sum: 2 },
            ],
            [
                [2n, [1, 2], [3n, 1n], 5, 4n, false],
                [3n, [1, 5], [1n, 3n, 2n], 21, 6n, false],
            ],
        ],
        [
            'keeps points apart when their bounds differ, they fall in different buckets, or they carry a trace',
            [
                { ts: 1n, buckets: [1n, 0n, 0n], sum: 1 },
                { ts: 2n, bounds: [1, 10], buckets: [0n, 1n, 0n], sum: 2 },
                { ts: NEXT_BUCKET, buckets: [0n, 0n, 1n], sum: 6 },
                { traced: true, ts: 3n, buckets: [0n, 1n, 0n], sum: 4 },
            ],
            [
                [1n, [1, 5], [1n, 0n, 0n], 1, 1n, false],
                [2n, [1, 10], [0n, 1n, 0n], 2, 1n, false],
                [3n, [1, 5], [0n, 1n, 0n], 4, 1n, true],
                [NEXT_BUCKET, [1, 5], [0n, 0n, 1n], 6, 1n, false],
            ],
        ],
        [
            'starts a new merged point before a count would pass the signed Avro long range',
            [
                { ts: 1n, buckets: [2n ** 62n, 0n, 0n], sum: 1 },
                { ts: 2n, buckets: [2n ** 62n, 0n, 0n], sum: 2 },
                { ts: 3n, buckets: [0n, 1n, 0n], sum: 3 },
            ],
            [
                [1n, [1, 5], [2n ** 62n, 0n, 0n], 1, 2n ** 62n, false],
                [3n, [1, 5], [2n ** 62n, 1n, 0n], 5, 2n ** 62n + 1n, false],
            ],
        ],
    ])('%s', (_name, points, expected) => {
        expect(summarizeHistograms(aggregateMetricRecords(points.map(histogram)))).toEqual(expected)
    })

    it('writes a merged histogram that the Avro writer schema accepts', () => {
        const nullable = (type: avro.schema.DefinedType): avro.Schema => ['null', type]
        const type = parseWriterSchema({
            type: 'record',
            name: 'MetricRecord',
            fields: [
                { name: 'timestamp', type: nullable({ type: 'long', logicalType: 'timestamp-micros' }) },
                { name: 'metric_type', type: nullable('string') },
                { name: 'value', type: nullable('double') },
                { name: 'count', type: nullable('long') },
                { name: 'histogram_bounds', type: nullable({ type: 'array', items: 'double' }) },
                { name: 'histogram_counts', type: nullable({ type: 'array', items: 'long' }) },
                { name: 'aggregation_temporality', type: nullable('string') },
                { name: 'series_fingerprint', type: nullable('long') },
            ],
        })
        const [merged] = aggregateMetricRecords(
            [
                { ts: 1n, buckets: [1n, 0n, 0n], sum: 1 },
                { ts: 2n, buckets: [0n, 2n, 0n], sum: 4 },
            ].map((point) => type.fromBuffer(type.toBuffer(histogram(point))))
        )
        expect(unwrap(type.fromBuffer(type.toBuffer(merged)).histogram_counts)).toEqual([1n, 2n, 0n])
    })
})
