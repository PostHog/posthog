import { AGGREGATION_BUCKET_MICROS, aggregateMetricRecords } from './aggregate-metric-records'
import { MetricRecord, unwrap } from './metric-record-avro'

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
            'passes through gauges, histograms, non-monotonic cumulative sums and cumulative sums without a start time',
            [
                { type: 'gauge', ts: 1n, value: 1 },
                { type: 'gauge', ts: 2n, value: 2 },
                { type: 'histogram', ts: 1n, value: 3 },
                { type: 'histogram', ts: 2n, value: 4 },
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
})
