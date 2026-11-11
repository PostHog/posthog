import { NodeKind } from '~/queries/schema/schema-general'

import { buildMetricsTableDrilldown } from './metricsTableDrilldown'

const CONFIG = {
    groupBy: 'http.route',
    dateRange: { date_from: '-3h' as const },
    interval: 'minute' as const,
    columns: [
        {
            label: 'Errors/s',
            metricName: 'http_server_requests_total',
            aggregation: 'rate' as const,
            filters: [{ key: 'http.response.status_code', op: 'regex' as const, value: '5..' }],
        },
        {
            label: 'p50 latency',
            metricName: 'http_server_request_duration_seconds',
            aggregation: 'histogram_quantile' as const,
            quantile: 0.5,
        },
    ],
}

describe('buildMetricsTableDrilldown', () => {
    it('builds one full chart query per column, split by the label of the table', () => {
        const [errors, latency] = buildMetricsTableDrilldown(CONFIG, ['GET /api/traces/{id}']).charts

        expect(errors.title).toEqual('Errors/s')
        expect(errors.query).toEqual({
            kind: NodeKind.MetricsQuery,
            dateRange: { date_from: '-3h' },
            interval: 'minute',
            clauses: [
                {
                    name: 'a',
                    metricName: 'http_server_requests_total',
                    aggregation: 'sum',
                    rangeFunction: 'rate',
                    filters: [
                        { key: 'http.response.status_code', op: 'regex', value: '5..' },
                        { key: 'http.route', op: 'regex', value: '^(?:GET /api/traces/\\{id\\})$' },
                    ],
                    groupBy: [{ key: 'http.route' }],
                },
            ],
        })
        expect(latency.query.clauses[0]).toMatchObject({ aggregation: 'histogram_quantile', quantile: 0.5 })
        expect(latency.query.clauses[0].rangeFunction).toBeUndefined()
    })

    it('escapes a dollar sign so a single row is not read as a dashboard variable', () => {
        const [errors] = buildMetricsTableDrilldown(CONFIG, ['/api/$tenant']).charts

        expect(errors.query.clauses[0].filters?.at(-1)).toEqual({
            key: 'http.route',
            op: 'regex',
            value: '^(?:/api/\\$tenant)$',
        })
    })

    it.each([
        ['keeps the point spacing for one row', '-1h', 'minute', null, 1, 'minute'],
        ['coarsens the point spacing for many rows over a long range', '-14d', 'minute', null, 50, 'hour_6'],
        ['picks about 60 points when the widget sets no interval', '-24h', null, null, 1, 'minute_30'],
        ['uses the dashboard interval over the widget one', '-24h', 'minute', { interval: 'hour' }, 1, 'hour'],
        [
            'coarsens a dashboard interval that would draw more than 500 points',
            '-1h',
            'minute',
            { date_from: '-30d', interval: 'minute' },
            1,
            'hour_6',
        ],
    ] as const)('%s', (_name, dateFrom, interval, dashboardFilters, rowCount, expectedInterval) => {
        const keys = Array.from({ length: rowCount }, (_, index) => `/api/${index}`)

        const drilldown = buildMetricsTableDrilldown(
            { ...CONFIG, dateRange: { date_from: dateFrom as '-1h' }, interval },
            keys,
            dashboardFilters
        )

        expect(drilldown.interval).toEqual(expectedInterval)
        expect(drilldown.charts.map((chart) => chart.query.interval)).toEqual([expectedInterval, expectedInterval])
    })

    it.each([
        ['the widget date range without a dashboard one', null, { date_from: '-3h' }],
        [
            'the dashboard date range over the widget one',
            { date_from: '-7d', date_to: '-1d' },
            { date_from: '-7d', date_to: '-1d' },
        ],
        [
            'a date-only dashboard end through the end of that day',
            { date_from: '2026-11-01', date_to: '2026-11-01' },
            { date_from: '2026-11-01', date_to: '2026-11-01T23:59:59' },
        ],
        [
            'an exact dashboard end as given',
            { date_from: '2026-11-01', date_to: '2026-11-02', explicitDate: true },
            { date_from: '2026-11-01', date_to: '2026-11-02' },
        ],
        ['the last 30 days of an open dashboard range over the limit', { date_from: '-90d' }, { date_from: '-30d' }],
        [
            'the last 30 days of a fixed dashboard range over the limit',
            { date_from: '2026-08-01', date_to: '2026-11-01' },
            { date_from: '2026-10-02T23:59:59', date_to: '2026-11-01T23:59:59' },
        ],
    ])('queries %s', (_name, dashboardFilters, expectedDateRange) => {
        const [errors] = buildMetricsTableDrilldown(CONFIG, ['/api/0'], dashboardFilters).charts

        expect(errors.query.dateRange).toEqual(expectedDateRange)
    })

    it('measures a dashboard range from midnight in the project timezone', () => {
        // 01:00 UTC is 17:00 the day before in Los Angeles, so "today" there is 17 hours long, not one.
        jest.useFakeTimers().setSystemTime(new Date('2026-11-10T01:00:00Z'))
        const keys = Array.from({ length: 50 }, (_, index) => `/api/${index}`)

        const drilldown = buildMetricsTableDrilldown(CONFIG, keys, { date_from: 'dStart' }, 'America/Los_Angeles')

        expect(drilldown.interval).toEqual('minute_15')
        jest.useRealTimers()
    })

    it('matches several rows with one anchored regex that escapes the values', () => {
        const [errors] = buildMetricsTableDrilldown(CONFIG, ['GET /api/traces/{id}', 'POST /api/chat']).charts

        expect(errors.query.clauses[0].filters?.at(-1)).toEqual({
            key: 'http.route',
            op: 'regex',
            value: '^(?:GET /api/traces/\\{id\\}|POST /api/chat)$',
        })
    })
})
