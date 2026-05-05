import { urls } from 'scenes/urls'

import { EventsNode, GroupNode, InsightVizNode, NodeKind, TrendsFilter } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    BreakdownType,
    ChartDisplayType,
    EventPropertyFilter,
    FilterLogicalOperator,
    InsightSceneSource,
    IntervalType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { BOT_ELIGIBLE_EVENTS } from './LiveWebAnalyticsMetricsTypes'

// The live tab has no global date picker; opened insights default to the same window the
// pre-built bot trends tabs use ("last 7 days") so users land on a populated chart instead
// of an empty one.
const DEFAULT_DATE_FROM = '-7d'
const DEFAULT_DATE_TO: string | null = null
const DEFAULT_INTERVAL: IntervalType = 'hour'

const PRODUCT_INTENT_HOST_PROPERTY = '$host'

type AnyEventsSeries = EventsNode | GroupNode

const buildHostFilter = (host: string | null): EventPropertyFilter[] =>
    host
        ? [
              {
                  key: PRODUCT_INTENT_HOST_PROPERTY,
                  value: [host],
                  operator: PropertyOperator.Exact,
                  type: PropertyFilterType.Event,
              },
          ]
        : []

const pageviewSeries = (custom_name?: string): EventsNode => ({
    kind: NodeKind.EventsNode,
    event: '$pageview',
    name: '$pageview',
    math: BaseMathType.UniqueUsers,
    custom_name,
})

const pageviewCountSeries = (custom_name?: string): EventsNode => ({
    kind: NodeKind.EventsNode,
    event: '$pageview',
    name: '$pageview',
    math: BaseMathType.TotalCount,
    custom_name,
})

// Combine bot-eligible events into one "Requests" series so opened insights have parity with
// the live tile (which counts $pageview, $pageleave, $screen, $http_log, $autocapture together).
const botRequestsSeries = (): GroupNode[] => {
    const nodes: EventsNode[] = BOT_ELIGIBLE_EVENTS.map((event) => ({
        kind: NodeKind.EventsNode,
        event,
        name: event,
        math: BaseMathType.TotalCount,
    }))
    return [
        {
            kind: NodeKind.GroupNode,
            name: BOT_ELIGIBLE_EVENTS.join(', '),
            custom_name: 'Requests',
            operator: FilterLogicalOperator.Or,
            nodes,
            math: BaseMathType.TotalCount,
        },
    ]
}

interface TrendsInsightArgs {
    series: AnyEventsSeries[]
    breakdown?: { breakdown: string; breakdown_type: BreakdownType; breakdown_limit?: number }
    properties?: EventPropertyFilter[]
    display?: ChartDisplayType
    interval?: IntervalType
    dateFrom?: string
    dateTo?: string | null
}

const buildTrendsInsightUrl = ({
    series,
    breakdown,
    properties,
    display = ChartDisplayType.ActionsLineGraph,
    interval = DEFAULT_INTERVAL,
    dateFrom = DEFAULT_DATE_FROM,
    dateTo = DEFAULT_DATE_TO,
}: TrendsInsightArgs): string => {
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            interval,
            series,
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: { display } as TrendsFilter,
            ...(breakdown ? { breakdownFilter: breakdown } : {}),
            ...(properties && properties.length > 0 ? { properties } : {}),
        },
    }
    return urls.insightNew({ query, sceneSource: 'web-analytics' as InsightSceneSource })
}

export interface LiveInsightUrlContext {
    host: string | null
}

// Each helper returns a URL for an "Open as new insight" button on the matching live tile.
// All helpers default to last 7d / hourly interval and inherit the host filter when set.

export const activeUsersChartInsightUrl = ({ host }: LiveInsightUrlContext): string =>
    buildTrendsInsightUrl({
        series: [pageviewSeries('Unique visitors')],
        properties: buildHostFilter(host),
        display: ChartDisplayType.ActionsBar,
    })

export const topPathsInsightUrl = ({ host }: LiveInsightUrlContext): string =>
    buildTrendsInsightUrl({
        series: [pageviewCountSeries('Pageviews')],
        breakdown: { breakdown: '$pathname', breakdown_type: 'event', breakdown_limit: 10 },
        properties: buildHostFilter(host),
        display: ChartDisplayType.ActionsBarValue,
    })

export const topReferrersInsightUrl = ({ host }: LiveInsightUrlContext): string =>
    buildTrendsInsightUrl({
        series: [pageviewCountSeries('Pageviews')],
        breakdown: { breakdown: '$referring_domain', breakdown_type: 'event', breakdown_limit: 10 },
        properties: buildHostFilter(host),
        display: ChartDisplayType.ActionsBarValue,
    })

export const devicesInsightUrl = ({ host }: LiveInsightUrlContext): string =>
    buildTrendsInsightUrl({
        series: [pageviewSeries('Unique visitors')],
        breakdown: { breakdown: '$device_type', breakdown_type: 'event' },
        properties: buildHostFilter(host),
        display: ChartDisplayType.ActionsPie,
    })

export const browsersInsightUrl = ({ host }: LiveInsightUrlContext): string =>
    buildTrendsInsightUrl({
        series: [pageviewSeries('Unique visitors')],
        breakdown: { breakdown: '$browser', breakdown_type: 'event' },
        properties: buildHostFilter(host),
        display: ChartDisplayType.ActionsPie,
    })

export const countriesInsightUrl = ({ host }: LiveInsightUrlContext): string =>
    buildTrendsInsightUrl({
        series: [pageviewSeries('Unique visitors')],
        breakdown: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
        properties: buildHostFilter(host),
        display: ChartDisplayType.WorldMap,
    })

const isBotFilter: EventPropertyFilter = {
    key: '$virt_is_bot',
    value: ['true'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

// Matches the clipboard reference: $http_log over time, filtered to bot traffic, broken down
// by bot name. Used as the bot-tile header CTA so users land on an explorable version of the
// "named bots" panel.
export const botTrafficBreakdownInsightUrl = ({ host }: LiveInsightUrlContext): string =>
    buildTrendsInsightUrl({
        series: botRequestsSeries(),
        breakdown: { breakdown: '$virt_bot_name', breakdown_type: 'event', breakdown_limit: 25 },
        properties: [isBotFilter, ...buildHostFilter(host)],
        display: ChartDisplayType.ActionsBarValue,
    })

export const botEventsChartInsightUrl = ({ host }: LiveInsightUrlContext): string =>
    buildTrendsInsightUrl({
        series: botRequestsSeries(),
        breakdown: { breakdown: '$virt_traffic_category', breakdown_type: 'event' },
        properties: [isBotFilter, ...buildHostFilter(host)],
        display: ChartDisplayType.ActionsBar,
    })

// Per-row click on the bot traffic tile — drills into a single bot's request volume over time,
// broken down by category so the user can see the same "bot · category" labels as on the tile.
export const botRowInsightUrl = ({
    host,
    botName,
    category,
}: LiveInsightUrlContext & { botName: string; category: string }): string => {
    const properties: EventPropertyFilter[] = [
        isBotFilter,
        {
            key: '$virt_bot_name',
            value: [botName],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
        ...buildHostFilter(host),
    ]
    if (category) {
        properties.push({
            key: '$virt_traffic_category',
            value: [category],
            operator: PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        })
    }
    return buildTrendsInsightUrl({
        series: botRequestsSeries(),
        properties,
        display: ChartDisplayType.ActionsLineGraph,
    })
}
