import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import { type Dashboard, GRID, type Tile } from '../dashboard/document/dashboardTypes'
import type { ChartConfig } from '../panels/chart/chartSpec'
import { type MetricOptions, metricSpec } from '../panels/chart/viz/metric/metricSpec'
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
const metric = (title: string, sql: string, format?: MetricOptions['format']): ContentPanel<ChartConfig> =>
    chart(title, sql, format ? { type: 'metric', options: { format } } : { type: 'metric' })
const line = (title: string, sql: string): ContentPanel<ChartConfig> => chart(title, sql, { type: 'line' })
const bar = (title: string, sql: string): ContentPanel<ChartConfig> => chart(title, sql, { type: 'bar' })
const text = (markdown: string): SavedPanel => ({
    type: 'markdown',
    config: { text: markdown },
    appearance: { backgroundColor: 'transparent' },
})

const tile = (id: string, x: number, y: number, w: number, h: number, panel: Tile['panel']): Tile => ({
    id,
    place: { x, y, w, h },
    panel,
})
const section = (id: string, x: number, y: number, w: number, title: string, tiles: Tile[], collapsed = false): Tile =>
    tile(id, x, y, w, GRID.collapsedSectionRows, { type: 'section', title, tiles, collapsed })

const METRIC_ROWS = metricSpec.size.h
// Spreads the leftover columns over the row, so five metrics still fill 24 columns.
const metricRow = (prefix: string, y: number, cols: number, metrics: ContentPanel<ChartConfig>[]): Tile[] => {
    const edge = (index: number): number => Math.round((index * cols) / metrics.length)
    return metrics.map((panel, index) =>
        tile(`${prefix}-${index}`, edge(index), y, edge(index + 1) - edge(index), METRIC_ROWS, panel)
    )
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
    loading: `${SQL.pageviewsOverTime} -- sample: loading`,
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
                ...metricRow('ks-metric', 0, 18, [
                    metric('Visitors', SQL.visitors),
                    metric('Sessions', SQL.sessions),
                    metric('Signups', SQL.signups),
                ]),
                tile('ks-metric-3', 18, 0, 6, METRIC_ROWS, { ...metric('Revenue', SQL.revenue, 'currency'), refreshedAt: REFRESHED_AT }),
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
                    tile('ks-n-metric', 0, 0, 6, METRIC_ROWS, metric('Errors', SQL.errors)),
                    tile('ks-n-metric2', 6, 0, 6, METRIC_ROWS, metric('Error rate', SQL.sessionErrorRate, 'percentage')),
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
                    tile('ks-q-currency', 12, 14, 6, METRIC_ROWS, metric('Revenue', SQL.revenue, 'currency')),
                    tile('ks-q-number', 18, 14, 6, METRIC_ROWS, metric('Signups', SQL.signups, 'number')),
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
            id: 'custom-panels',
            title: 'Custom panels',
            tiles: [
                tile(
                    'cp-intro',
                    0,
                    0,
                    24,
                    4,
                    text(
                        "**Custom panels** draw a product's own components in a tile. They have no menu or customizations unless the product opts in, and the browser list, period switcher and active hours change this dashboard's filters."
                    )
                ),
                tile('cp-setup', 0, 4, 24, 5, { type: 'custom', config: { content: 'kitchen-sink/setup-prompt' }, parts: { header: false } }),
                tile('cp-time', 0, 9, 24, 3, { type: 'custom', config: { content: 'kitchen-sink/time-range-shortcuts' }, parts: { header: false } }),
                tile('cp-browsers', 0, 12, 8, 8, { type: 'custom', title: 'Browsers', config: { content: 'kitchen-sink/browser-filter' } }),
                tile('cp-health', 8, 12, 8, 8, { type: 'custom', config: { content: 'kitchen-sink/health-checklist' }, parts: { header: false } }),
                tile('cp-line', 16, 12, 8, 8, line('Pageviews by browser', SQL.pageviewsOverTime)),
                tile('cp-issues', 0, 20, 12, 10, { type: 'custom', title: 'Top issues', config: { content: 'kitchen-sink/top-issues' } }),
                tile('cp-deck', 12, 20, 12, 5, { type: 'custom', config: { content: 'kitchen-sink/recommendation-deck' }, parts: { header: false } }),
                tile('cp-breakdown', 0, 30, 12, 14, { type: 'custom', title: 'Breakdown', config: { content: 'kitchen-sink/tabbed-breakdown' } }),
                tile('cp-heatmap', 12, 30, 12, 14, { type: 'custom', title: 'Active hours', config: { content: 'kitchen-sink/activity-heatmap' } }),
                tile('cp-live', 0, 44, 8, 8, { type: 'custom', title: 'Live', config: { content: 'kitchen-sink/live-visitors' } }),
                tile('cp-instrumentation', 8, 44, 16, 8, { type: 'custom', config: { content: 'kitchen-sink/instrumentation-checklist' }, parts: { header: false } }),
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
                    ...metricRow('ts-good-metric', 0, 24, [
                        metric('Number', SQL.signups, 'number'),
                        metric('Currency', SQL.revenue, 'currency'),
                        metric('Percentage', SQL.conversionRate, 'percentage'),
                        metric('No format', SQL.visitors),
                    ]),
                    tile('ts-good-line', 0, METRIC_ROWS, 8, 14, line('Line', SQL.signupsOverTime)),
                    tile('ts-good-bar', 8, METRIC_ROWS, 8, 14, bar('Bars by breakdown', SQL.sources)),
                    tile('ts-good-stacked', 16, METRIC_ROWS, 8, 14, chart('Stacked bars', SQL.eventsByType, { type: 'bar', options: { stack: true } })),
                    tile('ts-good-markdown', 0, METRIC_ROWS + 14, 24, 12, text(RICH_MARKDOWN)),
                    tile('ts-good-custom', 0, METRIC_ROWS + 26, 24, 4, { type: 'custom', config: { content: 'kitchen-sink/setup-prompt' }, parts: { header: false } }),
                ]),
                section('ts-loading', 0, 40, 24, 'Loading and refreshing', [
                    tile('ts-slow-line', 0, 0, 12, 12, { ...line('Slow query', SAMPLE.slow), description: 'The sample runner answers after 4 seconds' }),
                    tile('ts-slow-metric', 12, 0, 6, METRIC_ROWS, metric('Slow total', SAMPLE.slowTotal)),
                    tile('ts-stale', 18, 0, 6, 12, { ...line('Stale result', SAMPLE.stale), refreshedAt: REFRESHED_AT }),
                ]),
                section('ts-failed', 0, 54, 24, 'Empty and failed queries', [
                    tile('ts-empty-line', 0, 0, 8, 12, line('Empty result', SAMPLE.empty)),
                    tile('ts-empty-metric', 8, 0, 4, METRIC_ROWS, metric('Empty total', SAMPLE.emptyTotal)),
                    tile('ts-error-metric', 12, 0, 4, METRIC_ROWS, metric('Failed total', SAMPLE.error)),
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
                    tile('ts-unknown-viz', 16, 0, 8, 10, { type: 'chart', title: 'Unknown chart type', config: { query: { language: 'hogql', query: SQL.signups }, viz: { type: 'radar' } } }),
                    tile('ts-bad-options', 0, 10, 8, 10, { type: 'chart', title: 'Invalid chart options', config: { query: { language: 'hogql', query: SQL.signups }, viz: { type: 'metric', options: { format: 'banana' } } } }),
                    tile('ts-bad-markdown', 8, 10, 8, 10, { type: 'markdown', title: 'Invalid text config', config: { text: 42 } }),
                    tile('ts-bad-chart', 16, 10, 8, 10, { type: 'chart', title: 'Chart with no query', config: { viz: { type: 'line' } } }),
                    tile('ts-bad-custom', 0, 20, 8, 10, { type: 'custom', title: 'Unknown custom content', config: { content: 'kitchen-sink/missing' } }),
                ]),
                section('ts-appearance', 0, 104, 24, 'Tile appearance', [
                    tile('ts-headerless', 0, 0, 6, 8, { ...text('A tile with its header hidden.'), title: 'Hidden title', parts: { header: false } }),
                    tile('ts-long-title', 6, 0, 6, 8, {
                        ...metric('A very long title that is cut off at the edge of the tile instead of wrapping onto another line', SQL.visitors),
                        description: 'Hover the icon to read the description.',
                    }),
                    tile('ts-tinted', 12, 0, 6, 8, { ...metric('Blue background', SQL.sessions), appearance: { backgroundColor: 'var(--color-blue-500)' } }),
                    tile('ts-no-background', 18, 0, 6, 8, { ...text('No background and no border.'), appearance: { backgroundColor: 'transparent', border: false } }),
                ]),
                section('ts-kinds', 0, 112, 24, 'Other kinds of chart', [
                    tile('ts-kind-slow-pie', 0, 0, 6, 12, chart('Slow pie', SAMPLE.slow, { type: 'pie' })),
                    tile('ts-kind-empty-bar-list', 6, 0, 6, 12, chart('Empty bar list', SAMPLE.empty, { type: 'bar-list' })),
                    tile('ts-kind-empty-gauge', 12, 0, 6, 12, chart('Empty gauge', SAMPLE.emptyTotal, { type: 'gauge' })),
                    tile('ts-kind-error-heatmap', 18, 0, 6, 12, chart('Failed heatmap', SAMPLE.error, { type: 'heatmap' })),
                    tile('ts-kind-stale-funnel', 0, 12, 24, 12, { ...chart('Stale funnel', SAMPLE.stale, { type: 'funnel' }), refreshedAt: REFRESHED_AT }),
                ]),
                section('ts-skeletons', 0, 138, 24, 'Loading skeletons', [
                    tile('ts-skeleton-metric', 0, 0, 6, 10, chart('Metric', SAMPLE.loading, { type: 'metric' })),
                    tile('ts-skeleton-line', 6, 0, 6, 10, chart('Line', SAMPLE.loading, { type: 'line' })),
                    tile('ts-skeleton-bar', 12, 0, 6, 10, chart('Bar', SAMPLE.loading, { type: 'bar' })),
                    tile('ts-skeleton-area', 18, 0, 6, 10, chart('Area', SAMPLE.loading, { type: 'area' })),
                    tile('ts-skeleton-combo', 0, 10, 6, 10, chart('Bar and line', SAMPLE.loading, { type: 'combo' })),
                    tile('ts-skeleton-pie', 6, 10, 6, 10, chart('Pie', SAMPLE.loading, { type: 'pie' })),
                    tile('ts-skeleton-bar-list', 12, 10, 6, 10, chart('Bar list', SAMPLE.loading, { type: 'bar-list' })),
                    tile('ts-skeleton-proportion', 18, 10, 6, 10, chart('Proportion bar', SAMPLE.loading, { type: 'proportion' })),
                    tile('ts-skeleton-funnel', 0, 20, 6, 10, chart('Funnel', SAMPLE.loading, { type: 'funnel' })),
                    tile('ts-skeleton-gauge', 6, 20, 6, 10, chart('Gauge', SAMPLE.loading, { type: 'gauge' })),
                    tile('ts-skeleton-heatmap', 12, 20, 6, 10, chart('Heatmap', SAMPLE.loading, { type: 'heatmap' })),
                    tile('ts-skeleton-scatter', 18, 20, 6, 10, chart('Scatter', SAMPLE.loading, { type: 'scatter' })),
                    tile('ts-skeleton-box-plot', 0, 30, 6, 10, chart('Box plot', SAMPLE.loading, { type: 'box-plot' })),
                    tile('ts-skeleton-slope', 6, 30, 6, 10, chart('Slope', SAMPLE.loading, { type: 'slope' })),
                    tile('ts-skeleton-sankey', 12, 30, 6, 10, chart('Sankey', SAMPLE.loading, { type: 'sankey' })),
                    tile('ts-skeleton-flame-graph', 0, 40, 12, 10, chart('Flame graph', SAMPLE.loading, { type: 'flame-graph' })),
                ]),
            ],
        },
        {
            id: 'web-analytics',
            title: 'Web analytics',
            tiles: [
                ...metricRow('wa-metric', 0, 24, [
                    metric('Visitors', SQL.visitors),
                    metric('Page views', SQL.pageviews),
                    metric('Sessions', SQL.sessions),
                    metric('Session duration', SQL.sessionDuration),
                    metric('Bounce rate', SQL.bounceRate, 'percentage'),
                ]),
                tile('wa-trend', 0, 8, 24, 16, chart('Visitors and page views', SQL.eventsByType, { type: 'area' })),
                tile('wa-paths', 0, 24, 12, 10, chart('Top paths', SQL.paths, { type: 'bar-list' })),
                tile('wa-sources', 12, 24, 12, 10, chart('Top sources', SQL.sources, { type: 'bar-list' })),
                tile('wa-devices', 0, 34, 8, 14, chart('Device types', SQL.devices, { type: 'pie' })),
                tile('wa-geo', 8, 34, 8, 14, chart('Countries', SQL.countries, { type: 'bar-list' })),
                tile('wa-hours', 16, 34, 8, 14, chart('Active days', SQL.devices, { type: 'heatmap' })),
                section('wa-goals', 0, 48, 24, 'Goals', [
                    tile('wa-goal-funnel', 0, 0, 12, 14, chart('Visit to signup', SQL.paths, { type: 'funnel' })),
                    tile('wa-goal-trend', 12, 0, 12, 14, line('Goal conversions', SQL.signupsOverTime)),
                    tile('wa-goal-rate', 0, 14, 12, METRIC_ROWS, metric('Conversion rate', SQL.conversionRate, 'percentage')),
                    tile('wa-goal-total', 12, 14, 12, METRIC_ROWS, metric('Conversions', SQL.signups)),
                ]),
            ],
        },
        {
            id: 'ai-observability',
            title: 'AI observability',
            tiles: [
                ...metricRow('aio-metric', 0, 24, [
                    metric('Traces', SQL.traces),
                    metric('Generations', SQL.generations),
                    metric('Users', SQL.aiUsers),
                    metric('Total cost', SQL.aiCost, 'currency'),
                ]),
                tile('aio-cost', 0, 8, 16, 16, chart('Cost by model', SQL.costByModel, { type: 'area' })),
                tile('aio-cost-share', 16, 8, 8, 16, chart('Share of cost', SQL.costByModel, { type: 'pie' })),
                section('aio-usage', 0, 24, 24, 'Usage', [
                    tile('aio-calls', 0, 0, 16, 14, chart('Generations and errors', SQL.clicksAndSignups, { type: 'combo' })),
                    tile('aio-tokens', 16, 0, 8, 10, chart('Tokens by model', SQL.tokensByModel, { type: 'bar-list' })),
                    tile('aio-users', 0, 14, 12, 14, bar('Cost per user', SQL.costPerUser)),
                    tile('aio-models', 12, 14, 12, 14, chart('Cost change by model', SQL.costByModel, { type: 'slope' })),
                ]),
                section('aio-latency', 0, 52, 24, 'Latency', [
                    tile('aio-latency-trend', 0, 0, 12, 14, line('p95 generation latency', SQL.generationLatency)),
                    tile('aio-latency-spread', 12, 0, 12, 14, chart('Latency by model', SQL.tokensByModel, { type: 'box-plot' })),
                ]),
                section('aio-errors', 0, 70, 24, 'Errors', [
                    tile('aio-error-rate', 0, 0, 6, 10, metric('Error rate', SQL.aiErrorRate, 'percentage')),
                    tile('aio-error-trend', 6, 0, 18, 12, line('Errors over time', SQL.aiErrorsOverTime)),
                ]),
            ],
        },
        {
            id: 'apm',
            title: 'APM',
            tiles: [
                ...metricRow('apm-metric', 0, 20, [
                    metric('Requests', SQL.requests),
                    metric('Request rate', SQL.requestRate),
                    metric('Errors', SQL.requestErrors),
                    metric('Error rate', SQL.aiErrorRate, 'percentage'),
                ]),
                tile('apm-p95', 20, 0, 4, METRIC_ROWS, chart('p95 latency', SQL.p95, { type: 'gauge', options: { max: 3000 } })),
                tile('apm-requests', 0, 8, 12, 16, metrics('Requests and errors', 'sum by (status) (rate(http_server_requests_total[5m]))', { type: 'combo' })),
                tile('apm-latency', 12, 8, 12, 16, metrics('Latency', 'histogram_quantile(0.95, sum by (le) (rate(http_server_duration_bucket[5m])))', { type: 'line' })),
                tile('apm-latency-heatmap', 0, 24, 24, 14, metrics('Latency distribution', 'sum by (le) (rate(http_server_duration_bucket[5m]))', { type: 'heatmap' })),
                section('apm-endpoints', 0, 38, 24, 'Endpoints', [
                    tile('apm-slowest', 0, 0, 12, 14, traces('Slowest operations', 'posthog-web-django', { type: 'bar-list' })),
                    tile('apm-busiest', 12, 0, 12, 14, traces('Busiest operations', 'posthog-web-django', { type: 'bar', options: { stack: true } })),
                    tile('apm-spread', 0, 14, 12, 14, traces('Duration by operation', 'posthog-web-django', { type: 'box-plot' })),
                    tile('apm-scatter', 12, 14, 12, 14, traces('Span durations', 'posthog-web-django', { type: 'scatter' })),
                ]),
                section('apm-traces', 0, 70, 24, 'Traces', [
                    tile('apm-flow', 0, 0, 12, 16, traces('Service calls', 'posthog-web-django', { type: 'sankey' })),
                    tile('apm-flame', 12, 0, 12, 16, traces('Time by operation', 'posthog-web-django', { type: 'flame-graph' })),
                ]),
            ],
        },
        {
            id: 'marketing',
            title: 'Marketing analytics',
            tiles: [
                ...metricRow('mk-metric', 0, 24, [
                    metric('Ad clicks', SQL.adClicks),
                    metric('Ad visitors', SQL.adVisitors),
                    metric('Campaigns', SQL.campaigns),
                    metric('Signups from campaigns', SQL.adSignups),
                    metric('Clicks per visitor', SQL.clicksPerVisitor),
                    metric('Conversion rate', SQL.conversionRate, 'percentage'),
                ]),
                tile('mk-trend', 0, 8, 16, 16, chart('Ad clicks and signups', SQL.clicksAndSignups, { type: 'combo' })),
                tile('mk-funnel', 16, 8, 8, 16, chart('Click to signup', SQL.clicksAndSignups, { type: 'funnel' })),
                tile('mk-share', 0, 24, 24, 6, chart('Clicks by network', SQL.clicksAndSignups, { type: 'proportion' })),
                section('mk-google', 0, 30, 12, 'Google Ads', [
                    ...metricRow('mk-g', 0, 12, [metric('Clicks', SQL.googleClicks), metric('Visitors', SQL.googleVisitors)]),
                    tile('mk-g-bar', 0, 8, 12, 8, chart('Campaigns', SQL.googleCampaigns, { type: 'bar-list' })),
                    tile('mk-g-slope', 0, 16, 12, 12, chart('Campaign change', SQL.googleCampaigns, { type: 'slope' })),
                ]),
                section('mk-meta', 12, 30, 12, 'Meta Ads', [
                    ...metricRow('mk-m', 0, 12, [metric('Clicks', SQL.metaClicks), metric('Visitors', SQL.metaVisitors)]),
                    tile('mk-m-bar', 0, 8, 12, 8, chart('Campaigns', SQL.metaCampaigns, { type: 'bar-list' })),
                    tile('mk-m-slope', 0, 16, 12, 12, chart('Campaign change', SQL.metaCampaigns, { type: 'slope' })),
                ]),
            ],
        },
        {
            id: 'chart-kinds',
            title: 'Chart kinds',
            tiles: [
                tile('kind-intro', 0, 0, 24, 4, text('Every kind of chart quill draws, each from the query a team would give it. Change a tile\'s kind from its menu to compare kinds on the same data.')),
                section('kind-time', 0, 4, 24, 'Over time', [
                    tile('kind-line', 0, 0, 12, 14, line('Line', SQL.paths)),
                    tile('kind-bar', 12, 0, 12, 14, chart('Stacked bar', SQL.paths, { type: 'bar', options: { stack: true } })),
                    tile('kind-area', 0, 14, 12, 14, chart('Area', SQL.paths, { type: 'area' })),
                    tile('kind-combo', 12, 14, 12, 14, chart('Bar and line', SQL.clicksAndSignups, { type: 'combo' })),
                ]),
                section('kind-single', 0, 32, 24, 'One number', [
                    tile('kind-metric', 0, 0, 8, 10, metric('Metric card', SQL.signups)),
                    tile('kind-metric-currency', 8, 0, 8, 10, metric('Metric card, currency', SQL.revenue, 'currency')),
                    tile('kind-gauge', 16, 0, 8, 10, chart('Gauge', SQL.p95, { type: 'gauge', options: { max: 3000 } })),
                ]),
                section('kind-parts', 0, 44, 24, 'Parts of a whole', [
                    tile('kind-pie', 0, 0, 8, 14, chart('Pie', SQL.devices, { type: 'pie' })),
                    tile('kind-bar-list', 8, 0, 8, 14, chart('Bar list', SQL.sources, { type: 'bar-list' })),
                    tile('kind-funnel', 16, 0, 8, 14, chart('Funnel', SQL.paths, { type: 'funnel' })),
                    tile('kind-proportion', 0, 14, 24, 6, chart('Proportion bar', SQL.devices, { type: 'proportion' })),
                ]),
                section('kind-distribution', 0, 66, 24, 'Distribution and change', [
                    tile('kind-heatmap', 0, 0, 12, 14, chart('Heatmap', SQL.countries, { type: 'heatmap' })),
                    tile('kind-scatter', 12, 0, 12, 14, chart('Scatter', SQL.sources, { type: 'scatter' })),
                    tile('kind-box-plot', 0, 14, 12, 14, chart('Box plot', SQL.devices, { type: 'box-plot' })),
                    tile('kind-slope', 12, 14, 12, 14, chart('Slope', SQL.countries, { type: 'slope' })),
                ]),
                section('kind-flow', 0, 96, 24, 'Flows and trees', [
                    tile('kind-sankey', 0, 0, 12, 16, chart('Sankey', SQL.sources, { type: 'sankey' })),
                    tile('kind-flame-graph', 12, 0, 12, 16, traces('Flame graph', 'posthog-web-django', { type: 'flame-graph' })),
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
