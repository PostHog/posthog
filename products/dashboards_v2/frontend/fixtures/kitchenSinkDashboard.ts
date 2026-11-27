import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import { type Dashboard, GRID, type Tile } from '../dashboard/document/dashboardTypes'
import type { ChartConfig } from '../panels/chart/chartSpec'
import { type StatOptions, statSpec } from '../panels/chart/viz/stat/statSpec'
import { type PanelQuery } from '../query/querySchema'
import { type ContentPanel, type SavedPanel } from '../panels/core/panelSchema'

// TODO(2026-11-25): Delete once the board list can open saved boards.
// It stands in for a saved dashboard and shows every panel and layout case.

const chartOf = (title: string, query: PanelQuery, viz: ChartConfig['viz']): ContentPanel<ChartConfig> => ({
    type: 'chart',
    title,
    config: { query, viz },
})
const chart = (title: string, sql: string, viz: ChartConfig['viz']): ContentPanel<ChartConfig> =>
    chartOf(title, { language: 'hogql', query: sql }, viz)
const metrics = (title: string, promql: string, viz: ChartConfig['viz']): ContentPanel<ChartConfig> =>
    chartOf(title, { language: 'query', query: { kind: NodeKind.MetricsQuery, clauses: [], language: 'promql', promql } }, viz)
const traces = (title: string, service: string, viz: ChartConfig['viz']): ContentPanel<ChartConfig> =>
    chartOf(
        title,
        {
            language: 'query',
            query: { kind: NodeKind.TraceSpansAggregationQuery, dateRange: { date_from: '-24h' }, serviceNames: [service] },
        },
        viz
    )
const stat = (title: string, sql: string, format?: StatOptions['format']): ContentPanel<ChartConfig> =>
    chart(title, sql, format ? { type: 'stat', options: { format } } : { type: 'stat' })
const line = (title: string, sql: string): ContentPanel<ChartConfig> => chart(title, sql, { type: 'line' })
const bar = (title: string, sql: string): ContentPanel<ChartConfig> => chart(title, sql, { type: 'bar' })
const text = (markdown: string): SavedPanel => ({ type: 'markdown', config: { text: markdown } })

const tile = (id: string, x: number, y: number, w: number, h: number, panel: Tile['panel']): Tile => ({
    id,
    place: { x, y, w, h },
    panel,
})
const section = (id: string, x: number, y: number, w: number, title: string, tiles: Tile[], collapsed = false): Tile =>
    tile(id, x, y, w, GRID.collapsedSectionRows, { type: 'section', title, tiles, collapsed })

const STAT_ROWS = statSpec.size.h
const statRow = (prefix: string, y: number, cols: number, stats: ContentPanel<ChartConfig>[]): Tile[] => {
    const w = Math.floor(cols / stats.length)
    return stats.map((panel, index) => tile(`${prefix}-${index}`, index * w, y, w, STAT_ROWS, panel))
}

// The SQL reads the dashboard's time range through `{filters}`.
const total = (value: string, where: string): string => `select ${value} from events where (${where}) and {filters}`
const daily = (value: string, where: string, groupBy = 'day'): string =>
    `select toStartOfDay(timestamp) as day, ${value} from events where (${where}) and {filters} group by ${groupBy} order by day`
// One series per value of `breakdown`, kept to its five biggest values so the legend stays readable.
const dailyBy = (name: string, breakdown: string, value: string, where: string): string => {
    const scope = `(${where}) and isNotNull(${breakdown}) and {filters}`
    return (
        `select toStartOfDay(timestamp) as day, ${breakdown} as ${name}, ${value} from events where ${scope} ` +
        `and ${breakdown} in (select ${breakdown} from events where ${scope} group by ${breakdown} order by count() desc limit 5) ` +
        `group by day, ${name} order by day`
    )
}

const PAGEVIEW = "event = '$pageview'"
const SIGNUP = "event = 'user signed up'"
const EXCEPTION = "event = '$exception'"
const GENERATION = "event = '$ai_generation'"
const AI_EVENT = "event in ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')"
const AI_ERROR = 'properties.$ai_is_error = true'
const AI_COST = 'toFloat(properties.$ai_total_cost_usd)'
const AI_LATENCY = 'toFloat(properties.$ai_latency)'
const GOOGLE_AD = `${PAGEVIEW} and notEmpty(properties.gclid)`
const META_AD = `${PAGEVIEW} and notEmpty(properties.fbclid)`
const AD_CLICK = `${PAGEVIEW} and (notEmpty(properties.gclid) or notEmpty(properties.fbclid))`
// Revenue analytics views over project 2's Stripe source. `{filters}` only binds event-like tables, so these
// read the range directly.
const REVENUE_ITEM = 'stripe.prod.revenue_item_revenue_view'
const REVENUE_PRODUCT = 'stripe.prod.product_revenue_view'
const IN_RANGE = 'timestamp >= {filters.dateRange.from} and timestamp < {filters.dateRange.to}'

const SQL = {
    visitors: total('uniqExact(person_id) as visitors', PAGEVIEW),
    pageviews: total('count() as pageviews', PAGEVIEW),
    sessions: total('uniqExact($session_id) as sessions', PAGEVIEW),
    signups: total('count() as signups', SIGNUP),
    revenue: `select sum(amount) as revenue from ${REVENUE_ITEM} where ${IN_RANGE}`,
    errors: total('count() as errors', EXCEPTION),
    sessionErrorRate: total(
        "uniqExactIf($session_id, event = '$exception') / uniqExact($session_id) as error_rate",
        "event in ('$pageview', '$exception')"
    ),
    sessionDuration: 'select avg($session_duration) as session_duration from sessions where {filters}',
    bounceRate: 'select avg($is_bounce) as bounce_rate from sessions where {filters}',
    conversionRate: total(
        "countIf(event = 'user signed up') / uniqExactIf(person_id, event = '$pageview') as conversion_rate",
        "event in ('$pageview', 'user signed up')"
    ),
    signupsOverTime: daily('count() as signups', SIGNUP),
    activation: daily('uniqExact(person_id) as activated', "event = 'insight created'"),
    errorsOverTime: daily('count() as errors', EXCEPTION),
    pageviewsOverTime: daily('count() as pageviews', PAGEVIEW),
    visitorsOverTime: daily('uniqExact(person_id) as visitors', PAGEVIEW),
    signupsByCountry: dailyBy('country', 'properties.$geoip_country_code', 'count() as signups', SIGNUP),
    revenueByProduct:
        `select toStartOfDay(item.timestamp) as day, coalesce(product.name, item.product_id) as product, sum(item.amount) as revenue ` +
        `from ${REVENUE_ITEM} as item left join ${REVENUE_PRODUCT} as product on product.id = item.product_id ` +
        `where item.timestamp >= {filters.dateRange.from} and item.timestamp < {filters.dateRange.to} ` +
        `and item.product_id in (select product_id from ${REVENUE_ITEM} where ${IN_RANGE} group by product_id order by sum(amount) desc limit 5) ` +
        `group by day, product order by day`,
    eventsByType: daily('event, count() as events', "event in ('$pageview', '$autocapture', '$pageleave')", 'day, event'),
    paths: dailyBy('path', 'properties.$pathname', 'count() as pageviews', PAGEVIEW),
    sources: dailyBy('source', 'properties.$referring_domain', 'count() as pageviews', PAGEVIEW),
    devices: dailyBy('device', 'properties.$device_type', 'count() as pageviews', PAGEVIEW),
    countries: dailyBy('country', 'properties.$geoip_country_code', 'count() as pageviews', PAGEVIEW),
    // Many SDKs never send the `$ai_trace` root event, so a trace is any trace ID seen on an AI event.
    traces: total('uniqExact(properties.$ai_trace_id) as traces', `${AI_EVENT} and notEmpty(properties.$ai_trace_id)`),
    generations: total('count() as generations', GENERATION),
    aiUsers: total('uniqExact(distinct_id) as users', GENERATION),
    aiCost: total(`sum(${AI_COST}) as cost`, GENERATION),
    aiErrorRate: total(`countIf(${AI_ERROR}) / count() as error_rate`, GENERATION),
    costByModel: dailyBy('model', 'properties.$ai_model', `sum(${AI_COST}) as cost`, GENERATION),
    generationLatency: daily(`quantile(0.95)(${AI_LATENCY}) as p95_latency`, GENERATION),
    tokensByModel: dailyBy(
        'model',
        'properties.$ai_model',
        'sum(toFloat(properties.$ai_input_tokens) + toFloat(properties.$ai_output_tokens)) as tokens',
        GENERATION
    ),
    generationsOverTime: daily('count() as generations', GENERATION),
    costPerUser: daily(`sum(${AI_COST}) / uniqExact(distinct_id) as cost_per_user`, GENERATION),
    aiErrorsOverTime: daily(`countIf(${AI_ERROR}) as errors`, GENERATION),
    requests: total('count() as requests', GENERATION),
    // Divides by the selected range, not the span between the first and last generation, so idle time counts.
    requestRate: total(
        "count() / greatest(dateDiff('second', {filters.dateRange.from}, least({filters.dateRange.to}, now())), 1) as per_second",
        GENERATION
    ),
    requestErrors: total(`countIf(${AI_ERROR}) as errors`, GENERATION),
    p95: total(`quantile(0.95)(${AI_LATENCY}) as p95_latency`, GENERATION),
    adClicks: total('count() as clicks', AD_CLICK),
    adVisitors: total('uniqExact(person_id) as visitors', AD_CLICK),
    campaigns: total('uniqExact(properties.utm_campaign) as campaigns', AD_CLICK),
    adSignups: total('count() as signups', `${SIGNUP} and notEmpty(person.properties.$initial_utm_source)`),
    clicksPerVisitor: total('count() / uniqExact(person_id) as clicks_per_visitor', AD_CLICK),
    clicksAndSignups: daily(
        "if(event = 'user signed up', 'Signups', 'Ad clicks') as series, count() as events",
        `${AD_CLICK} or ${SIGNUP}`,
        'day, series'
    ),
    googleClicks: total('count() as clicks', GOOGLE_AD),
    googleVisitors: total('uniqExact(person_id) as visitors', GOOGLE_AD),
    googleCampaigns: dailyBy('campaign', 'properties.utm_campaign', 'count() as clicks', GOOGLE_AD),
    metaClicks: total('count() as clicks', META_AD),
    metaVisitors: total('uniqExact(person_id) as visitors', META_AD),
    metaCampaigns: dailyBy('campaign', 'properties.utm_campaign', 'count() as clicks', META_AD),
    insightsOverTime: daily('count() as insights', "event = 'insight created'"),
    createdByType: daily('event, count() as created', "event in ('insight created', 'dashboard created')", 'day, event'),
}

const SAMPLE = {
    empty: `select toStartOfDay(timestamp) as day, count() as events from events where false group by day order by day -- sample: empty`,
    emptyTotal: 'select count() as events from events where false -- sample: empty',
    error: 'select missing_column from events -- sample: error',
    slow: `${SQL.pageviewsOverTime} -- sample: slow`,
    slowTotal: `${SQL.pageviews} -- sample: slow`,
    stale: `${SQL.signupsOverTime} -- sample: stale`,
    malformed: `${SQL.visitorsOverTime} -- sample: malformed`,
}

const RICH_MARKDOWN = [
    '## Markdown',
    '',
    'Text tiles support **bold**, _italic_, `code` and [links](https://posthog.com/docs).',
    '',
    '- A list item',
    '- Another item',
    '',
    '| Metric | Owner |',
    '| --- | --- |',
    '| Signups | Growth |',
    '| Errors | Platform |',
].join('\n')

const REFRESHED_AT = '2026-11-19T09:00:00Z'

const BIG_TILE_COUNT = 120

export const kitchenSinkDashboard: Dashboard = {
    version: 2,
    title: 'Dashboards v2',
    description: 'Every panel, section and chart option on one dashboard.',
    time: { from: 'now-14d', to: 'now' },
    allowFilters: true,
    filters: [{ id: 'browser', type: 'property', label: 'Browser', config: { key: '$browser', source: 'event' } }],
    tabs: [
        {
            id: 'kitchen-sink',
            title: 'Kitchen sink',
            tiles: [
                ...statRow('ks-stat', 0, 18, [
                    stat('Visitors', SQL.visitors),
                    stat('Sessions', SQL.sessions),
                    stat('Signups', SQL.signups),
                ]),
                tile('ks-stat-3', 18, 0, 6, STAT_ROWS, { ...stat('Revenue', SQL.revenue, 'currency'), refreshedAt: REFRESHED_AT }),
                tile('ks-trend', 0, 8, 16, 16, { ...line('Signups over time', SQL.signupsOverTime), description: 'New accounts per day', refreshedAt: REFRESHED_AT }),
                tile('ks-notes', 16, 8, 8, 16, text('## Notes\n\nDrag a tile by its title. Resize it from its left, right or bottom edge.')),
                section('ks-section', 0, 24, 24, 'Section with tiles', [
                    tile('ks-s-bar', 0, 0, 12, 14, {
                        ...bar('Signups by country', SQL.signupsByCountry),
                        description: 'A longer description wraps inside the tooltip, so the header keeps its height whatever the text says.',
                    }),
                    tile('ks-s-line', 12, 0, 12, 14, line('Activation', SQL.activation)),
                ]),
                section('ks-nested', 0, 42, 24, 'Section with a section inside', [
                    tile('ks-n-stat', 0, 0, 6, STAT_ROWS, stat('Errors', SQL.errors)),
                    tile('ks-n-stat2', 6, 0, 6, STAT_ROWS, stat('Error rate', SQL.sessionErrorRate, 'percentage')),
                    section('ks-inner', 12, 0, 12, 'Inner section', [
                        tile('ks-i-line', 0, 0, 12, 12, line('Errors over time', SQL.errorsOverTime)),
                    ]),
                ]),
                section('ks-left', 0, 66, 12, 'Half width', [tile('ks-l-bar', 0, 0, 12, 12, bar('Revenue by product', SQL.revenueByProduct))]),
                section('ks-right', 12, 66, 12, 'Half width, empty', []),
                section('ks-closed', 0, 86, 24, 'Closed section', [tile('ks-c-line', 0, 0, 24, 12, line('Hidden', SQL.pageviewsOverTime))], true),
                tile('ks-headless', 0, 90, 8, 8, text('A tile without a title is dragged by its body.')),
                section('ks-queries', 0, 98, 24, 'Every query language and chart option', [
                    tile('ks-q-hogql', 0, 0, 8, 14, line('HogQL query', SQL.pageviewsOverTime)),
                    tile('ks-q-metrics', 8, 0, 8, 14, metrics('Metrics query', 'sum(rate(http_requests_total[5m]))', { type: 'line' })),
                    tile('ks-q-traces', 16, 0, 8, 14, traces('Trace query', 'posthog-web-django', { type: 'bar' })),
                    tile('ks-q-stacked', 0, 14, 12, 14, chart('Stacked bars', SQL.eventsByType, { type: 'bar', options: { stack: true } })),
                    tile('ks-q-currency', 12, 14, 6, STAT_ROWS, stat('Revenue', SQL.revenue, 'currency')),
                    tile('ks-q-number', 18, 14, 6, STAT_ROWS, stat('Signups', SQL.signups, 'number')),
                    tile('ks-q-insight', 12, 22, 12, 8, {
                        type: 'chart',
                        title: 'Insight query, last 24 hours',
                        config: {
                            query: {
                                language: 'query',
                                query: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
                            },
                            viz: { type: 'line' },
                            time: { from: 'now-24h', to: 'now' },
                        },
                    }),
                    tile('ks-q-multi', 0, 30, 24, 16, {
                        type: 'chart',
                        title: 'Several queries in one chart',
                        description: 'HogQL, a trends query, PromQL and LogQL, each named by its legend',
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
                                        language: 'query',
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
                                {
                                    refId: 'D',
                                    query: {
                                        language: 'logql',
                                        query: 'sum(count_over_time({service_name="posthog-web-django", level="error"}[5m]))',
                                    },
                                    legend: 'Error log lines per 5 minutes (LogQL)',
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
            id: 'tile-states',
            title: 'Tile states',
            tiles: [
                tile(
                    'ts-demo',
                    0,
                    0,
                    24,
                    4,
                    text(
                        '**Sample data.** A project that has not sent any events sees made-up charts instead of empty ones. ' +
                            '[Show this tab with sample data](/dashboard-v2?tab=tile-states&sample_data=true) or [with real data](/dashboard-v2?tab=tile-states).'
                    )
                ),
                section('ts-good', 0, 4, 24, 'Every panel type', [
                    ...statRow('ts-good-stat', 0, 24, [
                        stat('Number', SQL.signups, 'number'),
                        stat('Currency', SQL.revenue, 'currency'),
                        stat('Percentage', SQL.conversionRate, 'percentage'),
                        stat('No format', SQL.visitors),
                    ]),
                    tile('ts-good-line', 0, STAT_ROWS, 8, 14, line('Line', SQL.signupsOverTime)),
                    tile('ts-good-bar', 8, STAT_ROWS, 8, 14, bar('Bars by breakdown', SQL.sources)),
                    tile('ts-good-stacked', 16, STAT_ROWS, 8, 14, chart('Stacked bars', SQL.eventsByType, { type: 'bar', options: { stack: true } })),
                    tile('ts-good-markdown', 0, STAT_ROWS + 14, 24, 12, text(RICH_MARKDOWN)),
                ]),
                section('ts-loading', 0, 40, 24, 'Loading and refreshing', [
                    tile('ts-slow-line', 0, 0, 12, 12, { ...line('Slow query', SAMPLE.slow), description: 'The sample runner answers after 4 seconds' }),
                    tile('ts-slow-stat', 12, 0, 6, STAT_ROWS, stat('Slow total', SAMPLE.slowTotal)),
                    tile('ts-stale', 18, 0, 6, 12, { ...line('Stale result', SAMPLE.stale), refreshedAt: REFRESHED_AT }),
                ]),
                section('ts-failed', 0, 54, 24, 'Empty and failed queries', [
                    tile('ts-empty-line', 0, 0, 8, 12, line('Empty result', SAMPLE.empty)),
                    tile('ts-empty-stat', 8, 0, 4, STAT_ROWS, stat('Empty total', SAMPLE.emptyTotal)),
                    tile('ts-error-stat', 12, 0, 4, STAT_ROWS, stat('Failed total', SAMPLE.error)),
                    tile('ts-error-line', 16, 0, 8, 12, line('Failed query', SAMPLE.error)),
                    tile('ts-partial', 0, 12, 24, 14, {
                        type: 'chart',
                        title: 'One of two queries failed',
                        config: {
                            targets: [
                                { refId: 'A', query: { language: 'hogql', query: SQL.pageviewsOverTime }, legend: 'Pageviews' },
                                { refId: 'B', query: { language: 'hogql', query: SAMPLE.error }, legend: 'Broken' },
                            ],
                            viz: { type: 'line' },
                        },
                    }),
                ]),
                section('ts-broken', 0, 82, 24, 'Broken tiles', [
                    tile('ts-throws', 0, 0, 8, 10, { ...line('Panel throws', SAMPLE.malformed), description: 'The sample runner returns a frame without fields' }),
                    tile('ts-unknown-type', 8, 0, 8, 10, { type: 'heatmap', title: 'Unknown panel type', config: {} }),
                    tile('ts-unknown-viz', 16, 0, 8, 10, { type: 'chart', title: 'Unknown chart type', config: { query: { language: 'hogql', query: SQL.signups }, viz: { type: 'pie' } } }),
                    tile('ts-bad-options', 0, 10, 8, 10, { type: 'chart', title: 'Invalid chart options', config: { query: { language: 'hogql', query: SQL.signups }, viz: { type: 'stat', options: { format: 'banana' } } } }),
                    tile('ts-bad-markdown', 8, 10, 8, 10, { type: 'markdown', title: 'Invalid text config', config: { text: 42 } }),
                    tile('ts-bad-chart', 16, 10, 8, 10, { type: 'chart', title: 'Chart with no query', config: { viz: { type: 'line' } } }),
                ]),
                section('ts-appearance', 0, 104, 24, 'Tile appearance', [
                    tile('ts-headerless', 0, 0, 6, 8, { ...text('A tile with its header hidden.'), title: 'Hidden title', parts: { header: false } }),
                    tile('ts-long-title', 6, 0, 6, 8, {
                        ...stat('A very long title that is cut off at the edge of the tile instead of wrapping onto another line', SQL.visitors),
                        description: 'Hover the icon to read the description.',
                    }),
                    tile('ts-tinted', 12, 0, 6, 8, { ...stat('Blue background', SQL.sessions), appearance: { backgroundColor: 'var(--color-blue-500)' } }),
                    tile('ts-no-background', 18, 0, 6, 8, { ...text('No background and no border.'), appearance: { backgroundColor: 'transparent', border: false } }),
                ]),
            ],
        },
        {
            id: 'web-analytics',
            title: 'Web analytics',
            tiles: [
                ...statRow('wa-stat', 0, 24, [
                    stat('Visitors', SQL.visitors),
                    stat('Page views', SQL.pageviews),
                    stat('Sessions', SQL.sessions),
                    stat('Session duration', SQL.sessionDuration),
                    stat('Bounce rate', SQL.bounceRate, 'percentage'),
                ]),
                tile('wa-trend', 0, 8, 24, 18, line('Unique visitors', SQL.visitorsOverTime)),
                tile('wa-paths', 0, 26, 12, 18, bar('Paths', SQL.paths)),
                tile('wa-sources', 12, 26, 12, 18, bar('Sources', SQL.sources)),
                tile('wa-devices', 0, 44, 12, 16, bar('Device types', SQL.devices)),
                tile('wa-geo', 12, 44, 12, 16, bar('Countries', SQL.countries)),
                section('wa-goals', 0, 60, 24, 'Goals', [
                    tile('wa-goal-trend', 0, 0, 16, 14, line('Goal conversions', SQL.signupsOverTime)),
                    tile('wa-goal-rate', 16, 0, 8, STAT_ROWS, stat('Conversion rate', SQL.conversionRate, 'percentage')),
                    tile('wa-goal-total', 16, 8, 8, 8, stat('Conversions', SQL.signups)),
                ]),
            ],
        },
        {
            id: 'ai-observability',
            title: 'AI observability',
            tiles: [
                ...statRow('aio-stat', 0, 24, [
                    stat('Traces', SQL.traces),
                    stat('Generations', SQL.generations),
                    stat('Users', SQL.aiUsers),
                    stat('Total cost', SQL.aiCost, 'currency'),
                ]),
                tile('aio-cost', 0, 8, 12, 16, line('Cost by model', SQL.costByModel)),
                tile('aio-latency', 12, 8, 12, 16, line('Generation latency', SQL.generationLatency)),
                section('aio-usage', 0, 24, 24, 'Usage', [
                    tile('aio-tokens', 0, 0, 8, 14, bar('Tokens by model', SQL.tokensByModel)),
                    tile('aio-calls', 8, 0, 8, 14, line('Generations over time', SQL.generationsOverTime)),
                    tile('aio-users', 16, 0, 8, 14, bar('Cost per user', SQL.costPerUser)),
                ]),
                section('aio-errors', 0, 42, 24, 'Errors', [
                    tile('aio-error-rate', 0, 0, 6, STAT_ROWS, stat('Error rate', SQL.aiErrorRate, 'percentage')),
                    tile('aio-error-trend', 6, 0, 18, 12, line('Errors over time', SQL.aiErrorsOverTime)),
                ]),
            ],
        },
        {
            id: 'apm',
            title: 'APM',
            tiles: [
                ...statRow('apm-stat', 0, 24, [
                    stat('Requests', SQL.requests),
                    stat('Request rate', SQL.requestRate),
                    stat('Errors', SQL.requestErrors),
                    stat('Error rate', SQL.aiErrorRate, 'percentage'),
                    stat('p95', SQL.p95),
                ]),
                tile('apm-requests', 0, 8, 12, 16, metrics('Requests and errors', 'sum by (status) (rate(http_server_requests_total[5m]))', { type: 'line' })),
                tile('apm-latency', 12, 8, 12, 16, metrics('Latency', 'histogram_quantile(0.95, sum by (le) (rate(http_server_duration_bucket[5m])))', { type: 'line' })),
                section('apm-endpoints', 0, 24, 24, 'Endpoints', [
                    tile('apm-slowest', 0, 0, 12, 16, traces('Slowest operations', 'posthog-web-django', { type: 'bar' })),
                    tile('apm-busiest', 12, 0, 12, 16, traces('Busiest operations', 'posthog-web-django', { type: 'bar', options: { stack: true } })),
                ]),
            ],
        },
        {
            id: 'marketing',
            title: 'Marketing analytics',
            tiles: [
                ...statRow('mk-stat', 0, 24, [
                    stat('Ad clicks', SQL.adClicks),
                    stat('Ad visitors', SQL.adVisitors),
                    stat('Campaigns', SQL.campaigns),
                    stat('Signups from campaigns', SQL.adSignups),
                    stat('Clicks per visitor', SQL.clicksPerVisitor),
                    stat('Conversion rate', SQL.conversionRate, 'percentage'),
                ]),
                tile('mk-trend', 0, 8, 24, 16, line('Ad clicks and signups', SQL.clicksAndSignups)),
                section('mk-google', 0, 24, 12, 'Google Ads', [
                    ...statRow('mk-g', 0, 12, [stat('Clicks', SQL.googleClicks), stat('Visitors', SQL.googleVisitors)]),
                    tile('mk-g-bar', 0, 8, 12, 12, bar('Campaigns', SQL.googleCampaigns)),
                ]),
                section('mk-meta', 12, 24, 12, 'Meta Ads', [
                    ...statRow('mk-m', 0, 12, [stat('Clicks', SQL.metaClicks), stat('Visitors', SQL.metaVisitors)]),
                    tile('mk-m-bar', 0, 8, 12, 12, bar('Campaigns', SQL.metaCampaigns)),
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
                    index % 3 === 0
                        ? bar(`Bar ${index}`, SQL.createdByType)
                        : line(`Line ${index}`, SQL.insightsOverTime)
                )
            ),
        },
    ],
}
