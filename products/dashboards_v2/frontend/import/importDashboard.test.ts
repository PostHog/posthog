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
        [
            'a legend the query endpoint rejects',
            JSON.stringify({
                panels: [
                    {
                        type: 'timeseries',
                        title: 'Up',
                        targets: [{ refId: 'A', expr: 'up', legendFormat: 'x'.repeat(1001) }],
                    },
                ],
            }),
            "can't be opened",
        ],
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
            'Plan mix': 'partial',
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
})
