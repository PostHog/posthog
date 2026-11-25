import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import type { WidgetQuery } from '../dashboard/dashboardSchema'
import { type ContentWidget, type Dashboard, GRID, type Tile } from '../dashboard/dashboardTypes'
import type { ChartConfig } from '../widgets/chart/chartSpec'
import { type StatOptions, statSpec } from '../widgets/chart/viz/stat/statSpec'

const chartOf = (title: string, query: WidgetQuery, viz: ChartConfig['viz']): ContentWidget<ChartConfig> => ({
    type: 'chart',
    title,
    config: { query, viz },
})
const chart = (title: string, sql: string, viz: ChartConfig['viz']): ContentWidget<ChartConfig> =>
    chartOf(title, { language: 'hogql', query: sql }, viz)
const metrics = (title: string, promql: string, viz: ChartConfig['viz']): ContentWidget<ChartConfig> =>
    chartOf(title, { language: 'metrics', query: { kind: NodeKind.MetricsQuery, clauses: [], language: 'promql', promql } }, viz)
const traces = (title: string, service: string, viz: ChartConfig['viz']): ContentWidget<ChartConfig> =>
    chartOf(
        title,
        {
            language: 'traces',
            query: { kind: NodeKind.TraceSpansAggregationQuery, dateRange: { date_from: '-24h' }, serviceNames: [service] },
        },
        viz
    )
const stat = (title: string, format?: StatOptions['format']): ContentWidget<ChartConfig> =>
    chart(title, `select count() as ${title}`, format ? { type: 'stat', options: { format } } : { type: 'stat' })
const line = (title: string): ContentWidget<ChartConfig> =>
    chart(title, `select count() from events where chart = '${title}' by day`, { type: 'line' })
const bar = (title: string): ContentWidget<ChartConfig> =>
    chart(title, `select count() from events where chart = '${title}' by country`, { type: 'bar' })
const text = (markdown: string): ContentWidget => ({ type: 'markdown', config: { text: markdown } })

const tile = (id: string, x: number, y: number, w: number, h: number, widget: Tile['widget']): Tile => ({
    id,
    place: { x, y, w, h },
    widget,
})
const section = (id: string, x: number, y: number, w: number, title: string, tiles: Tile[], collapsed = false): Tile =>
    tile(id, x, y, w, GRID.collapsedSectionRows, { type: 'section', title, tiles, collapsed })

const STAT_ROWS = statSpec.size.h
const statRow = (prefix: string, y: number, cols: number, titles: string[]): Tile[] => {
    const w = Math.floor(cols / titles.length)
    return titles.map((title, index) => tile(`${prefix}-${index}`, index * w, y, w, STAT_ROWS, stat(title)))
}

const REFRESHED_AT = '2026-11-19T09:00:00Z'

const BIG_TILE_COUNT = 120

export const kitchenSinkDashboard: Dashboard = {
    version: 2,
    title: 'Dashboards v2',
    description: 'Every widget, section and chart option on one dashboard.',
    time: { from: 'now-14d', to: 'now' },
    tabs: [
        {
            id: 'kitchen-sink',
            title: 'Kitchen sink',
            tiles: [
                ...statRow('ks-stat', 0, 18, ['Visitors', 'Sessions', 'Signups']),
                tile('ks-stat-3', 18, 0, 6, STAT_ROWS, { ...stat('Revenue'), refreshedAt: REFRESHED_AT }),
                tile('ks-trend', 0, 8, 16, 16, { ...line('Signups over time'), description: 'New accounts per day', refreshedAt: REFRESHED_AT }),
                tile('ks-notes', 16, 8, 8, 16, text('## Notes\n\nDrag a tile by its title. Resize it from its left, right or bottom edge.')),
                section('ks-section', 0, 24, 24, 'Section with tiles', [
                    tile('ks-s-bar', 0, 0, 12, 14, {
                        ...bar('Signups by country'),
                        description: 'A longer description wraps inside the tooltip, so the header keeps its height whatever the text says.',
                    }),
                    tile('ks-s-line', 12, 0, 12, 14, line('Activation')),
                ]),
                section('ks-nested', 0, 42, 24, 'Section with a section inside', [
                    tile('ks-n-stat', 0, 0, 6, STAT_ROWS, stat('Errors')),
                    tile('ks-n-stat2', 6, 0, 6, STAT_ROWS, stat('Error rate', 'percentage')),
                    section('ks-inner', 12, 0, 12, 'Inner section', [
                        tile('ks-i-line', 0, 0, 12, 12, line('Errors over time')),
                    ]),
                ]),
                section('ks-left', 0, 66, 12, 'Half width', [tile('ks-l-bar', 0, 0, 12, 12, bar('Plans'))]),
                section('ks-right', 12, 66, 12, 'Half width, empty', []),
                section('ks-closed', 0, 86, 24, 'Closed section', [tile('ks-c-line', 0, 0, 24, 12, line('Hidden'))], true),
                tile('ks-headless', 0, 90, 8, 8, text('A tile without a title is dragged by its body.')),
                section('ks-queries', 0, 98, 24, 'Every query language and chart option', [
                    tile('ks-q-hogql', 0, 0, 8, 14, line('HogQL query')),
                    tile('ks-q-metrics', 8, 0, 8, 14, metrics('Metrics query', 'sum(rate(http_requests_total[5m]))', { type: 'line' })),
                    tile('ks-q-traces', 16, 0, 8, 14, traces('Trace query', 'checkout', { type: 'bar' })),
                    tile('ks-q-stacked', 0, 14, 12, 14, chart('Stacked bars', 'select count() from events by plan', { type: 'bar', options: { stack: true } })),
                    tile('ks-q-currency', 12, 14, 6, STAT_ROWS, stat('Revenue', 'currency')),
                    tile('ks-q-number', 18, 14, 6, STAT_ROWS, stat('Signups', 'number')),
                    tile('ks-q-insight', 12, 22, 12, 8, {
                        type: 'chart',
                        title: 'Insight query, last 24 hours',
                        config: {
                            query: {
                                language: 'insight',
                                query: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
                            },
                            viz: { type: 'line' },
                            time: { from: 'now-24h', to: 'now' },
                        },
                    }),
                    tile('ks-q-multi', 0, 30, 24, 16, {
                        type: 'chart',
                        title: 'Several queries in one chart',
                        description: 'HogQL, a trends query and PromQL, each named by its legend',
                        config: {
                            targets: [
                                {
                                    refId: 'A',
                                    query: {
                                        language: 'hogql',
                                        query: "select toStartOfHour(timestamp) as hour, count() as pageviews from events where event = '$pageview' and {filters} group by hour order by hour",
                                    },
                                    legend: 'Pageviews (HogQL)',
                                },
                                {
                                    refId: 'B',
                                    query: {
                                        language: 'insight',
                                        query: {
                                            kind: NodeKind.TrendsQuery,
                                            interval: 'hour',
                                            series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.UniqueUsers }],
                                        },
                                    },
                                    legend: 'Unique viewers (trends)',
                                },
                                {
                                    refId: 'C',
                                    query: { language: 'promql', query: 'sum(rate(http_requests_total[5m]))' },
                                    legend: 'Requests per second (PromQL)',
                                },
                            ],
                            viz: { type: 'line' },
                            time: { from: 'now-6h', to: 'now' },
                        },
                    }),
                ]),
            ],
        },
        {
            id: 'web-analytics',
            title: 'Web analytics',
            tiles: [
                ...statRow('wa-stat', 0, 24, ['Visitors', 'Page views', 'Sessions', 'Session duration', 'Bounce rate']),
                tile('wa-trend', 0, 8, 24, 18, line('Unique visitors')),
                tile('wa-paths', 0, 26, 12, 18, bar('Paths')),
                tile('wa-sources', 12, 26, 12, 18, bar('Sources')),
                tile('wa-devices', 0, 44, 12, 16, bar('Device types')),
                tile('wa-geo', 12, 44, 12, 16, bar('Countries')),
                section('wa-goals', 0, 60, 24, 'Goals', [
                    tile('wa-goal-trend', 0, 0, 16, 14, line('Goal conversions')),
                    tile('wa-goal-rate', 16, 0, 8, STAT_ROWS, stat('Conversion rate', 'percentage')),
                    tile('wa-goal-total', 16, 8, 8, 8, stat('Conversions')),
                ]),
            ],
        },
        {
            id: 'ai-observability',
            title: 'AI observability',
            tiles: [
                ...statRow('aio-stat', 0, 24, ['Traces', 'Generations', 'Users', 'Total cost']),
                tile('aio-cost', 0, 8, 12, 16, line('Cost by model')),
                tile('aio-latency', 12, 8, 12, 16, line('Generation latency')),
                section('aio-usage', 0, 24, 24, 'Usage', [
                    tile('aio-tokens', 0, 0, 8, 14, bar('Tokens by model')),
                    tile('aio-calls', 8, 0, 8, 14, line('Generations over time')),
                    tile('aio-users', 16, 0, 8, 14, bar('Cost per user')),
                ]),
                section('aio-errors', 0, 42, 24, 'Errors', [
                    tile('aio-error-rate', 0, 0, 6, STAT_ROWS, stat('Error rate', 'percentage')),
                    tile('aio-error-trend', 6, 0, 18, 12, line('Errors over time')),
                ]),
            ],
        },
        {
            id: 'apm',
            title: 'APM',
            tiles: [
                ...statRow('apm-stat', 0, 24, ['Requests', 'Request rate', 'Errors', 'Error rate', 'p95']),
                tile('apm-requests', 0, 8, 12, 16, metrics('Requests and errors', 'sum by (status) (rate(http_server_requests_total[5m]))', { type: 'line' })),
                tile('apm-latency', 12, 8, 12, 16, metrics('Latency', 'histogram_quantile(0.95, sum by (le) (rate(http_server_duration_bucket[5m])))', { type: 'line' })),
                section('apm-endpoints', 0, 24, 24, 'Endpoints', [
                    tile('apm-slowest', 0, 0, 12, 16, traces('Slowest operations', 'checkout', { type: 'bar' })),
                    tile('apm-busiest', 12, 0, 12, 16, traces('Busiest operations', 'checkout', { type: 'bar', options: { stack: true } })),
                ]),
            ],
        },
        {
            id: 'marketing',
            title: 'Marketing analytics',
            tiles: [
                ...statRow('mk-stat', 0, 24, ['Spend', 'Clicks', 'Impressions', 'Conversions', 'CPC', 'ROAS']),
                tile('mk-trend', 0, 8, 24, 16, line('Spend and conversions')),
                section('mk-google', 0, 24, 12, 'Google Ads', [
                    ...statRow('mk-g', 0, 12, ['Spend', 'ROAS']),
                    tile('mk-g-bar', 0, 8, 12, 12, bar('Campaigns')),
                ]),
                section('mk-meta', 12, 24, 12, 'Meta Ads', [
                    ...statRow('mk-m', 0, 12, ['Spend', 'ROAS']),
                    tile('mk-m-bar', 0, 8, 12, 12, bar('Campaigns')),
                ]),
            ],
        },
        { id: 'link-docs', title: 'Docs', href: 'https://posthog.com/docs/product-analytics/dashboards' },
        { id: 'link-v1', title: 'Dashboards', href: '/dashboard' },
        {
            id: 'big',
            title: `${BIG_TILE_COUNT} tiles`,
            tiles: Array.from({ length: BIG_TILE_COUNT }, (_, index) =>
                tile(
                    `big-${index}`,
                    (index % 4) * 6,
                    Math.floor(index / 4) * 12,
                    6,
                    12,
                    index % 3 === 0 ? bar(`Bar ${index}`) : line(`Line ${index}`)
                )
            ),
        },
    ],
}
