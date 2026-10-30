import { NodeKind } from '~/queries/schema/schema-general'

import { buildMetricsTableDrilldownQueries } from './metricsTableDrilldown'

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

describe('buildMetricsTableDrilldownQueries', () => {
    it('builds one full chart query per column, split by the label of the table', () => {
        const [errors, latency] = buildMetricsTableDrilldownQueries(CONFIG, ['GET /api/traces/{id}'])

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
        const [errors] = buildMetricsTableDrilldownQueries(CONFIG, ['/api/$tenant'])

        expect(errors.query.clauses[0].filters?.at(-1)).toEqual({
            key: 'http.route',
            op: 'regex',
            value: '^(?:/api/\\$tenant)$',
        })
    })

    it.each([
        ['keeps the point spacing for one row', '-1h', 1, 'minute'],
        ['coarsens the point spacing for many rows over a long range', '-14d', 50, 'hour_6'],
    ])('%s', (_name, dateFrom, rowCount, expectedInterval) => {
        const keys = Array.from({ length: rowCount }, (_, index) => `/api/${index}`)

        const [errors] = buildMetricsTableDrilldownQueries(
            { ...CONFIG, dateRange: { date_from: dateFrom as '-1h' } },
            keys
        )

        expect(errors.query.interval).toEqual(expectedInterval)
    })

    it('matches several rows with one anchored regex that escapes the values', () => {
        const [errors] = buildMetricsTableDrilldownQueries(CONFIG, ['GET /api/traces/{id}', 'POST /api/chat'])

        expect(errors.query.clauses[0].filters?.at(-1)).toEqual({
            key: 'http.route',
            op: 'regex',
            value: '^(?:GET /api/traces/\\{id\\}|POST /api/chat)$',
        })
    })
})
