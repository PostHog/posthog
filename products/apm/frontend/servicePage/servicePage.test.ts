import { parseTagsFilter } from 'lib/utils/url'

import { PropertyOperator } from '~/types'

import type { Span } from 'products/tracing/frontend/types'

import {
    ENVIRONMENT_KEYS,
    bucketIntervalLabel,
    latencyPercentileSeries,
    mergeRequestsSeries,
    serviceScopeFilters,
    serviceTracesUrl,
    topErrorGroups,
} from './servicePage'

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
    it('narrows the default environment to spans without any environment key', () => {
        const filters = serviceScopeFilters({ environment: '', version: null, operation: null }, null)
        expect(filters.map(({ key, operator }) => [key, operator])).toEqual(
            ENVIRONMENT_KEYS.map((key) => [key, PropertyOperator.IsNotSet])
        )
    })

    it('breaks the latency lines at buckets with no spans instead of dropping to zero', () => {
        const percentiles = latencyPercentileSeries([
            { time: 't0', count: 4, p50_ns: 20_000_000, p95_ns: 24_000_000, p99_ns: 31_000_000 },
            { time: 't1', count: 0, p50_ns: null, p95_ns: null, p99_ns: null },
        ])
        expect(percentiles).toEqual({
            times: ['t0', 't1'],
            p50: [20_000_000, NaN],
            p95: [24_000_000, NaN],
            p99: [31_000_000, NaN],
        })
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

    it('groups error spans by message, falling back to exception type, HTTP status, then span name', () => {
        const spans = [
            // The exception event's message outranks the span attributes.
            {
                ...errorSpan(6, { 'error.type': 'ValueError' }),
                events: [{ name: 'exception', timestamp: null, attributes: { 'exception.message': 'card declined' } }],
            },
            errorSpan(5, { 'exception.message': 'timeout', 'error.type': 'TimeoutError' }),
            errorSpan(4, { 'error.type': 'TimeoutError', 'http.response.status_code': '504' }),
            errorSpan(3, { 'http.response.status_code': '402' }),
            errorSpan(2, { 'http.status_code': '402' }),
            errorSpan(1, { 'exception.message': 'timeout' }),
            errorSpan(0, { 'exception.message': '402' }),
            { ...errorSpan(7, {}), name: 'POST /pay' },
        ]
        expect(
            topErrorGroups(spans).map(({ kind, value, count, latest }) => [kind, value, count, latest.span_id])
        ).toEqual([
            ['message', 'timeout', 2, 'span-5'],
            ['http_status', '402', 2, 'span-3'],
            ['message', 'card declined', 1, 'span-6'],
            ['exception_type', 'TimeoutError', 1, 'span-4'],
            ['message', '402', 1, 'span-0'],
            ['span_name', 'POST /pay', 1, 'span-7'],
        ])
    })

    it.each([
        [['2024-01-01T00:00:00Z', '2024-01-01T00:02:00Z'], '2 min'],
        [['2024-01-01T00:00:00Z', '2024-01-01T00:01:00Z'], 'minute'],
        [['2024-01-01T00:00:00Z', '2024-01-01T01:00:00Z'], 'hour'],
        [['2024-01-01T00:00:00Z', '2024-01-01T00:00:30Z'], '30 s'],
        [['2024-01-01T00:00:00Z'], null],
    ])('names the bar width of %j as %p', (times, expected) => {
        expect(bucketIntervalLabel(times)).toEqual(expected)
    })

    it('the traces link keeps a service name with a comma as one service', () => {
        const url = new URL(
            serviceTracesUrl('checkout,v2', { date_from: '-1h', date_to: null }, []),
            'https://app.example.com'
        )
        expect(parseTagsFilter(url.searchParams.get('serviceNames'))).toEqual(['checkout,v2'])
    })
})
