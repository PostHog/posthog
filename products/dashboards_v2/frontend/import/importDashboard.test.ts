import type { Tile } from '../dashboard/dashboardTypes'
import { validateDashboard } from '../dashboard/validateDashboard'
import { DEFAULT_PANELS } from '../panels/defaultPanels'
import { type ImportResult, importDashboard } from './importDashboard'
import { grafanaClassic, grafanaV2, newRelic } from './importFixtures'

function imported(input: unknown, prefix = ''): ImportResult {
    const result = importDashboard(prefix + JSON.stringify(input))
    if ('error' in result) {
        throw new Error(result.error)
    }
    return result
}

function tilesOf(tiles: Tile[]): Tile[] {
    return tiles.flatMap((tile) =>
        tile.panel.type === 'section' ? [tile, ...tilesOf((tile.panel as any).tiles)] : [tile]
    )
}

function byTitle(result: ImportResult): Record<string, any> {
    const all = result.dashboard.tabs.flatMap((tab) => ('tiles' in tab ? tilesOf(tab.tiles) : []))
    return Object.fromEntries(all.map((tile) => [(tile.panel as any).title, tile]))
}

function statuses(result: ImportResult): Record<string, string> {
    return Object.fromEntries(result.report.tiles.map((tile) => [tile.title, tile.status]))
}

describe('importDashboard', () => {
    test.each([
        ['Grafana', grafanaClassic, 'grafana'],
        ['Grafana 12', grafanaV2, 'grafana-v2'],
        ['New Relic', newRelic, 'newrelic'],
    ])('turns a %s export into a valid board', (_name, input, source) => {
        const result = imported(input, 'Exported dashboard ')
        expect(result.report.source).toBe(source)
        expect(validateDashboard(result.dashboard, DEFAULT_PANELS)).toEqual([])
    })

    test.each([
        ['not JSON', 'dashboard', "This isn't JSON"],
        ['JSON of another tool', '{"widgets": []}', "doesn't look like"],
    ])('explains input it can not read: %s', (_name, text, error) => {
        expect(importDashboard(text)).toEqual({ error: expect.stringContaining(error) })
    })

    it('maps a classic Grafana board: rows, panel types, PromQL, LogQL and variables', () => {
        const result = imported(grafanaClassic)
        const tiles = byTitle(result)

        expect(result.dashboard.time).toEqual({ from: 'now-24h', to: 'now' })
        expect(tiles['Success rate'].panel.config).toEqual({
            query: { language: 'promql', query: 'sum(rate(checkout_ok_total)) / sum(rate(checkout_total))' },
            viz: { type: 'stat', options: { format: 'percentage' } },
        })
        expect(tiles['Requests by route'].panel.config.targets).toEqual([
            {
                refId: 'A',
                query: { language: 'promql', query: 'sum by (route) (rate(http_requests_total{region="eu"}))' },
                legend: '{{route}}',
            },
        ])
        expect(tiles['Error logs'].panel.config.targets).toEqual([
            {
                refId: 'A',
                query: {
                    language: 'logql',
                    query: 'sum by (k8s.pod.name) (count_over_time({k8s.namespace.name="shop"} |= "error" [5m]))',
                },
                legend: '{{k8s.pod.name}}',
            },
        ])
        expect(tiles['Errors'].panel).toMatchObject({ type: 'section' })
        expect(tiles['Errors'].panel.tiles.map((tile: Tile) => (tile.panel as any).title)).toEqual([
            'Errors by code',
            'Error logs',
        ])
        expect(tiles['Database'].panel).toMatchObject({ type: 'section', collapsed: true })
        expect(tiles['Errors by code'].place).toEqual({ x: 0, y: 0, w: 12, h: 14 })
        expect(tiles['Runbook'].panel).toEqual({
            type: 'markdown',
            title: 'Runbook',
            config: { text: 'Page the **checkout** owner.' },
        })
        expect(tiles['Latency'].panel.config.text).toContain('**Not supported yet:** heatmap')
        expect(tiles['Slow queries'].panel.config.text).toContain('SELECT query FROM slow_log')

        expect(statuses(result)).toEqual({
            'Success rate': 'mapped',
            'Requests by route': 'mapped',
            'Errors by code': 'mapped',
            'Error logs': 'mapped',
            'Slow queries': 'unsupported',
            Latency: 'unsupported',
            Runbook: 'mapped',
        })
        expect(result.report.requires).toEqual({
            events: [],
            properties: [],
            metrics: [
                'checkout_ok_total',
                'checkout_total',
                'db_latency_bucket',
                'http_errors_total',
                'http_requests_total',
            ],
            logStreams: ['{k8s.namespace.name="shop"}'],
        })
        expect(result.report.variables).toEqual([{ name: 'region', kind: 'custom', value: 'eu' }])
        expect(result.report.notes).toEqual([
            expect.stringContaining('variables'),
            expect.stringContaining('30s'),
            expect.stringContaining('utc'),
        ])
    })

    it('maps Grafana 12 tabs, collapsed rows and multi-value variables, and flags MetricsQL', () => {
        const result = imported(grafanaV2)
        const tiles = byTitle(result)

        expect(result.dashboard.tabs.map((tab) => tab.title)).toEqual(['Overview', 'Details'])
        expect(tiles['Queue depth'].panel.config.targets[0].query.query).toBe(
            'sum(queue_depth{service=~"worker-a|worker-b"})'
        )
        expect(tiles['Lag'].panel).toMatchObject({ type: 'section', collapsed: true })
        expect(tiles['Lag spread'].panel.config.targets[0].query.query).toBe(
            'quantiles("p", 0.5, 0.9, max_over_time(queue_lag_seconds))'
        )
        expect(result.report.tiles.find((tile) => tile.title === 'Lag spread')).toMatchObject({
            status: 'partial',
            reasons: [expect.stringContaining('quantiles()')],
        })
        expect(statuses(result)['Worker logs']).toBe('unsupported')
        expect(result.dashboard.time).toEqual({ from: 'now-6h', to: 'now' })
    })

    const panelWith = (overrides: Record<string, any>): Record<string, any> => ({
        type: 'timeseries',
        title: 'P',
        gridPos: { x: 0, y: 0, w: 12, h: 8 },
        datasource: { type: 'prometheus', uid: 'prom' },
        ...overrides,
    })
    const host = { name: 'host', type: 'custom', multi: true, current: { value: ['a.example.com'] } }

    test.each([
        [
            'a PromQL label inequality stays PromQL',
            panelWith({ datasource: null, targets: [{ refId: 'A', expr: 'requests_total{status!="200"}' }] }),
            { language: 'promql', query: 'requests_total{status!="200"}' },
            'mapped',
        ],
        [
            'a multi-value variable is regex-escaped',
            panelWith({ targets: [{ refId: 'A', expr: 'up{instance=~"$host"}' }] }),
            { language: 'promql', query: 'up{instance=~"a\\\\.example\\\\.com"}' },
            'mapped',
        ],
        [
            'a LogQL range macro gets a fixed window',
            panelWith({
                datasource: { type: 'loki', uid: 'loki' },
                targets: [{ refId: 'A', expr: 'rate({app="x"} |= "by (pod)" [$__auto])' }],
            }),
            { language: 'logql', query: 'rate({service_name="x"} |= "by (pod)" [1m])' },
            'partial',
        ],
        [
            "a percent stat is scaled to the stat's fraction",
            panelWith({
                type: 'stat',
                fieldConfig: { defaults: { unit: 'percent' } },
                targets: [{ refId: 'A', expr: 'cpu_pct' }],
            }),
            { language: 'promql', query: '(cpu_pct) / 100' },
            'mapped',
        ],
        [
            'a mean reducer is reported',
            panelWith({ type: 'stat', options: { reduceOptions: { calcs: ['mean'] } }, targets: [{ expr: 'up' }] }),
            { language: 'promql', query: 'up' },
            'partial',
        ],
        [
            'transformations are reported',
            panelWith({ transformations: [{ id: 'calculateField' }], targets: [{ expr: 'up' }] }),
            { language: 'promql', query: 'up' },
            'partial',
        ],
    ])('%s', (_name, panel, query, status) => {
        const result = imported({ title: 'T', templating: { list: [host] }, panels: [panel] })
        expect(byTitle(result)['P'].panel.config.query).toEqual(query)
        expect(result.report.tiles[0].status).toBe(status)
    })

    it('requires metrics named by __name__, and keeps a query that would close the note fence inside it', () => {
        const result = imported({
            title: 'T',
            time: { from: '11/25/2026', to: 'now' },
            panels: [
                panelWith({ targets: [{ expr: '{__name__="requests_total"}' }] }),
                panelWith({
                    title: 'SQL',
                    datasource: { type: 'grafana-postgresql-datasource' },
                    targets: [{ rawSql: 'SELECT 1\n```\n# injected' }],
                }),
            ],
        })
        expect(result.report.requires.metrics).toEqual(['requests_total'])
        expect(byTitle(result)['SQL'].panel.config.text).toContain('````sql\n-- A')
        expect(result.dashboard.time).toBeUndefined()
    })

    it('keeps refIds unique when shortening them to the board limit', () => {
        const long = 'r'.repeat(250)
        const result = imported({
            title: 'T',
            panels: [
                panelWith({
                    targets: [
                        { refId: `${long}1`, expr: 'up' },
                        { refId: `${long}2`, expr: 'down' },
                    ],
                }),
            ],
        })
        expect(validateDashboard(result.dashboard, DEFAULT_PANELS)).toEqual([])
    })

    it('reads plugin identifiers from a v2alpha1 export', () => {
        const result = imported({
            elements: {
                p: {
                    kind: 'Panel',
                    spec: {
                        title: 'P',
                        vizConfig: { kind: 'timeseries', spec: {} },
                        data: {
                            spec: {
                                queries: [
                                    { spec: { refId: 'A', query: { kind: 'prometheus', spec: { expr: 'up' } } } },
                                ],
                            },
                        },
                    },
                },
            },
            layout: { kind: 'GridLayout', spec: { items: [{ spec: { element: { name: 'p' }, width: 12 } }] } },
        })
        expect(statuses(result)).toEqual({ P: 'mapped' })
    })

    it('maps a New Relic board: pages, layout, NRQL, time ranges and fallbacks', () => {
        const result = imported(newRelic)
        const tiles = byTitle(result)

        expect(result.dashboard.tabs.map((tab) => tab.title)).toEqual(['Orders', 'Refunds'])
        expect(result.dashboard.time).toEqual({ from: 'now-1w', to: 'now' })
        expect(tiles['Buyers'].place).toEqual({ x: 6, y: 0, w: 18, h: 15 })
        expect(tiles['Orders'].panel.config).toEqual({
            query: {
                language: 'hogql',
                query: "select count() as count from events where event = 'OrderPlaced' and {filters}",
            },
            viz: { type: 'stat' },
        })
        expect(tiles['Orders by plan'].panel.config.viz).toEqual({ type: 'bar', options: { stack: true } })
        expect(tiles['Last half hour'].panel.config.time).toEqual({ from: 'now-30m', to: 'now' })
        expect(tiles['Orders'].panel.config.time).toBeUndefined()
        expect(tiles['Host CPU'].panel.config.text).toContain('FROM Metric')

        expect(statuses(result)).toEqual({
            Orders: 'mapped',
            Buyers: 'mapped',
            'Orders by plan': 'mapped',
            'Plan mix': 'unsupported',
            'Last half hour': 'mapped',
            '': 'mapped',
            'Refund rate': 'partial',
            'Host CPU': 'unsupported',
            'Checkout funnel': 'unsupported',
        })
        expect(result.report.queries).toEqual({ total: 9, translated: 6 })
        expect(result.report.requires).toMatchObject({
            events: ['OrderPlaced'],
            properties: ['plan', 'refunded', 'userId'],
        })
        expect(JSON.stringify(result.dashboard)).not.toContain('1234567')
    })

    it('keeps a New Relic widget whose visualization is named like an object property as a note', () => {
        const widget = {
            title: 'Odd',
            visualization: { id: '__proto__' },
            rawConfiguration: { nrqlQueries: [{ query: 'SELECT count(*) FROM OrderPlaced TIMESERIES' }] },
        }
        const result = imported({ name: 'Odd', pages: [{ name: 'Page', widgets: [widget] }] })

        expect(statuses(result)).toEqual({ Odd: 'unsupported' })
    })

    it('gives each column of a New Relic line chart its own query and leaves out a query with another time range', () => {
        const widget = {
            title: 'Latency',
            visualization: { id: 'viz.line' },
            rawConfiguration: {
                nrqlQueries: [
                    { query: 'SELECT percentile(latencyMs, 50, 95) FROM OrderPlaced TIMESERIES SINCE 1 day ago' },
                    { query: 'SELECT count(*) FROM OrderPlaced TIMESERIES SINCE 1 week ago' },
                ],
            },
        }
        const result = imported({ name: 'Latency', pages: [{ name: 'Page', widgets: [widget] }] })
        const queries = byTitle(result)['Latency'].panel.config.targets.map((target: any) => target.query.query)

        expect(queries).toEqual([expect.stringContaining('as p50 from'), expect.stringContaining('as p95 from')])
        expect(result.report.tiles[0]).toMatchObject({
            status: 'partial',
            reasons: [expect.stringContaining('different time range'), expect.stringContaining('1 of its 2 queries')],
        })
    })
})
