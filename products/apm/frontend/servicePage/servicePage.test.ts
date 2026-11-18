import type { Span } from 'products/tracing/frontend/types'

import { latencyPercentileSeries, mergeRequestsSeries, spanErrorMessage, topErrorMessages } from './servicePage'

const errorSpan = (n: number, attributes: Record<string, string>): Span => ({
    uuid: `uuid-${n}`,
    trace_id: `trace-${n}`,
    span_id: `span-${n}`,
    parent_span_id: '',
    name: 'GET /cart',
    kind: 2,
    service_name: 'checkout',
    status_code: 2,
    timestamp: `2024-01-01T00:0${n}:00Z`,
    end_time: `2024-01-01T00:0${n}:01Z`,
    duration_nano: 1,
    is_root_span: true,
    matched_filter: true,
    attributes,
    resource_attributes: {},
})

describe('servicePage', () => {
    it('reads each percentile off the bucket where the cumulative count crosses it', () => {
        const percentiles = latencyPercentileSeries({
            timeBuckets: ['t0', 't1'],
            // 1ms, 2ms and 5ms buckets. t0 has 90 fast, 8 medium and 2 slow spans; t1 is empty.
            bucketsNs: [1_000_000, 2_000_000, 5_000_000],
            labels: [],
            cells: [
                [90, 0],
                [8, 0],
                [2, 0],
            ],
        })
        // Upper bucket edges: 1ms → 2ms, 2ms → 5ms, 5ms → 10ms.
        expect(percentiles.p50).toEqual([2_000_000, NaN])
        expect(percentiles.p95).toEqual([5_000_000, NaN])
        expect(percentiles.p99).toEqual([10_000_000, NaN])
    })

    it('stacks errors under the rest of the requests and fills buckets without errors with zero', () => {
        expect(
            mergeRequestsSeries(
                [
                    { time: '2024-01-01T00:01:00Z', count: 5 },
                    { time: '2024-01-01T00:00:00Z', count: 10 },
                ],
                [{ time: '2024-01-01T00:00:00Z', count: 3 }]
            )
        ).toEqual({
            times: ['2024-01-01T00:00:00Z', '2024-01-01T00:01:00Z'],
            requests: [7, 5],
            errors: [3, 0],
        })
    })

    it('groups error spans by their most specific message, most frequent first', () => {
        const spans = [
            errorSpan(3, { 'exception.message': 'timeout', 'error.type': 'TimeoutError' }),
            errorSpan(2, { 'error.type': '503' }),
            errorSpan(1, { 'exception.message': 'timeout' }),
            errorSpan(0, {}),
        ]
        const top = topErrorMessages(spans)
        expect(top.map(({ message, count, latest }) => [message, count, latest.span_id])).toEqual([
            ['timeout', 2, 'span-3'],
            ['503', 1, 'span-2'],
            [spanErrorMessage(spans[3]), 1, 'span-0'],
        ])
    })
})
