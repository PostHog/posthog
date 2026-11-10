import { AGGREGATION_BUCKET_MICROS, aggregateMetricRecords } from './aggregate-metric-records'
import { MetricRecord, unwrap } from './metric-record-avro'

type Point = {
    type?: string
    temporality?: string
    monotonic?: boolean
    fingerprint?: bigint
    traced?: boolean
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
    ts,
    value,
}: Point) => ({
    metric_type: { string: type },
    aggregation_temporality: { string: temporality },
    is_monotonic: { boolean: monotonic },
    series_fingerprint: { long: fingerprint },
    timestamp: { long: BASE_TS + ts },
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
            'keeps the cumulative points around a reset, also when the value climbs past its old level',
            [
                { temporality: 'cumulative', ts: 1n, value: 100 },
                { temporality: 'cumulative', ts: 2n, value: 400 },
                { temporality: 'cumulative', ts: 3n, value: 900 },
                { temporality: 'cumulative', ts: 4n, value: 5 },
                { temporality: 'cumulative', ts: 5n, value: 1000 },
                { temporality: 'cumulative', ts: 6n, value: 1200 },
            ],
            [
                ['1', 1n, 100, 1n, false],
                ['1', 3n, 900, 2n, false],
                ['1', 4n, 5, 1n, false],
                ['1', 6n, 1200, 2n, false],
            ],
        ],
        [
            'passes through gauges, histograms and non-monotonic cumulative sums',
            [
                { type: 'gauge', ts: 1n, value: 1 },
                { type: 'gauge', ts: 2n, value: 2 },
                { type: 'histogram', ts: 1n, value: 3 },
                { type: 'histogram', ts: 2n, value: 4 },
                { temporality: 'cumulative', monotonic: false, ts: 1n, value: 9 },
                { temporality: 'cumulative', monotonic: false, ts: 2n, value: 8 },
            ],
            [
                ['1', 1n, 1, 1n, false],
                ['1', 1n, 3, 1n, false],
                ['1', 1n, 9, 1n, false],
                ['1', 2n, 2, 1n, false],
                ['1', 2n, 4, 1n, false],
                ['1', 2n, 8, 1n, false],
            ],
        ],
    ])('%s', (_name, points, expected) => {
        expect(summarize(aggregateMetricRecords(points.map(record)))).toEqual(expected.sort(bySeriesTimeValue))
    })
})
