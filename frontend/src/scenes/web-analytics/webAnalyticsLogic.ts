import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import { windowValues } from 'kea-window-values'
import api from 'lib/api'
import { FEATURE_FLAGS, RETENTION_FIRST_TIME, STALE_EVENT_SECONDS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getDefaultInterval, isNotNil, updateDatesWithInterval } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    NodeKind,
    QuerySchema,
    WebAnalyticsPropertyFilter,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
} from '~/queries/schema'
import { isWebAnalyticsPropertyFilters } from '~/queries/schema-guards'
import {
    BaseMathType,
    ChartDisplayType,
    EventDefinition,
    EventDefinitionType,
    InsightLogicProps,
    InsightType,
    IntervalType,
    PropertyDefinition,
    PropertyFilterType,
    PropertyOperator,
    RetentionPeriod,
} from '~/types'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'

export interface WebTileLayout {
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    colSpanClassName?: `md:col-span-${number}` | 'md:col-span-full'
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    rowSpanClassName?: `md:row-span-${number}`
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    orderWhenLargeClassName?: `xxl:order-${number}`
    className?: string
}

export enum TileId {
    OVERVIEW = 'OVERVIEW',
    GRAPHS = 'GRAPHS',
    PATHS = 'PATHS',
    SOURCES = 'SOURCES',
    DEVICES = 'DEVICES',
    GEOGRAPHY = 'GEOGRAPHY',
    RETENTION = 'RETENTION',
}

const loadPriorityMap: Record<TileId, number> = {
    [TileId.OVERVIEW]: 1,
    [TileId.GRAPHS]: 2,
    [TileId.PATHS]: 3,
    [TileId.SOURCES]: 4,
    [TileId.DEVICES]: 5,
    [TileId.GEOGRAPHY]: 6,
    [TileId.RETENTION]: 7,
}

interface BaseTile {
    tileId: TileId
    layout: WebTileLayout
}

export interface QueryTile extends BaseTile {
    title?: string
    query: QuerySchema
    showIntervalSelect?: boolean
    showPathCleaningControls?: boolean
    insightProps: InsightLogicProps
    canOpenModal: boolean
    canOpenInsight?: boolean
}

export interface TabsTile extends BaseTile {
    activeTabId: string
    setTabId: (id: string) => void
    tabs: {
        id: string
        title: string
        linkText: string
        query: QuerySchema
        showIntervalSelect?: boolean
        showPathCleaningControls?: boolean
        insightProps: InsightLogicProps
        canOpenModal?: boolean
        canOpenInsight?: boolean
    }[]
}

export type WebDashboardTile = QueryTile | TabsTile

export interface WebDashboardModalQuery {
    tileId: TileId
    tabId?: string
    title?: string
    query: QuerySchema
    insightProps: InsightLogicProps
    showIntervalSelect?: boolean
    showPathCleaningControls?: boolean
    canOpenInsight?: boolean
}

export enum GraphsTab {
    UNIQUE_USERS = 'UNIQUE_USERS',
    PAGE_VIEWS = 'PAGE_VIEWS',
    NUM_SESSION = 'NUM_SESSION',
}

export enum SourceTab {
    REFERRING_DOMAIN = 'REFERRING_DOMAIN',
    CHANNEL = 'CHANNEL',
    UTM_SOURCE = 'UTM_SOURCE',
    UTM_MEDIUM = 'UTM_MEDIUM',
    UTM_CAMPAIGN = 'UTM_CAMPAIGN',
    UTM_CONTENT = 'UTM_CONTENT',
    UTM_TERM = 'UTM_TERM',
}

export enum DeviceTab {
    BROWSER = 'BROWSER',
    OS = 'OS',
    DEVICE_TYPE = 'DEVICE_TYPE',
}

export enum PathTab {
    PATH = 'PATH',
    INITIAL_PATH = 'INITIAL_PATH',
}

export enum GeographyTab {
    MAP = 'MAP',
    COUNTRIES = 'COUNTRIES',
    REGIONS = 'REGIONS',
    CITIES = 'CITIES',
}

export interface WebAnalyticsStatusCheck {
    isSendingPageViews: boolean
    isSendingPageLeaves: boolean
    isSendingPageLeavesScroll: boolean
}

export const GEOIP_PLUGIN_URLS = [
    'https://github.com/PostHog/posthog-plugin-geoip',
    'https://www.npmjs.com/package/@posthog/geoip-plugin',
]

export const initialWebAnalyticsFilter = [] as WebAnalyticsPropertyFilters
const initialDateFrom = '-7d' as string | null
const initialDateTo = null as string | null
const initialInterval = getDefaultInterval(initialDateFrom, initialDateTo)

const getDashboardItemId = (section: TileId, tab: string | undefined, isModal?: boolean): `new-${string}` => {
    // pretend to be a new-AdHoc to get the correct behaviour elsewhere
    return `new-AdHoc.web-analytics.${section}.${tab || 'default'}.${isModal ? 'modal' : 'default'}`
}
export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsPropertyFilters) => ({ webAnalyticsFilters }),
        togglePropertyFilter: (
            type: PropertyFilterType.Event | PropertyFilterType.Person,
            key: string,
            value: string | number,
            tabChange?: {
                graphsTab?: string
                sourceTab?: string
                deviceTab?: string
                pathTab?: string
                geographyTab?: string
            }
        ) => ({
            type,
            key,
            value,
            tabChange,
        }),
        setGraphsTab: (tab: string) => ({
            tab,
        }),
        setSourceTab: (tab: string) => ({
            tab,
        }),
        setDeviceTab: (tab: string) => ({
            tab,
        }),
        setPathTab: (tab: string) => ({
            tab,
        }),
        setGeographyTab: (tab: string) => ({ tab }),
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setIsPathCleaningEnabled: (isPathCleaningEnabled: boolean) => ({ isPathCleaningEnabled }),
        setStateFromUrl: (state: {
            filters: WebAnalyticsPropertyFilters
            dateFrom: string | null
            dateTo: string | null
            interval: IntervalType | null
            graphsTab: string | null
            sourceTab: string | null
            deviceTab: string | null
            pathTab: string | null
            geographyTab: string | null
            isPathCleaningEnabled: boolean | null
        }) => ({
            state,
        }),
        openModal: (tileId: TileId, tabId?: string) => {
            return { tileId, tabId }
        },
        closeModal: () => ({}),
        openAsNewInsight: (tileId: TileId, tabId?: string) => {
            return { tileId, tabId }
        },
    }),
    reducers({
        webAnalyticsFilters: [
            initialWebAnalyticsFilter,
            {
                setWebAnalyticsFilters: (_, { webAnalyticsFilters }) => webAnalyticsFilters,
                togglePropertyFilter: (oldPropertyFilters, { key, value, type }): WebAnalyticsPropertyFilters => {
                    const similarFilterExists = oldPropertyFilters.some(
                        (f) => f.type === type && f.key === key && f.operator === PropertyOperator.Exact
                    )
                    if (similarFilterExists) {
                        // if there's already a matching property, turn it off or merge them
                        return oldPropertyFilters
                            .map((f) => {
                                if (f.key !== key || f.type !== type || f.operator !== PropertyOperator.Exact) {
                                    return f
                                }
                                const oldValue = (Array.isArray(f.value) ? f.value : [f.value]).filter(isNotNil)
                                let newValue: (string | number)[]
                                if (oldValue.includes(value)) {
                                    // If there are multiple values for this filter, reduce that to just the one being clicked
                                    if (oldValue.length > 1) {
                                        newValue = [value]
                                    } else {
                                        return null
                                    }
                                } else {
                                    newValue = [...oldValue, value]
                                }
                                return {
                                    type: PropertyFilterType.Event,
                                    key,
                                    operator: PropertyOperator.Exact,
                                    value: newValue,
                                } as const
                            })
                            .filter(isNotNil)
                    } else {
                        // no matching property, so add one
                        const newFilter: WebAnalyticsPropertyFilter = {
                            type,
                            key,
                            value,
                            operator: PropertyOperator.Exact,
                        }

                        return [...oldPropertyFilters, newFilter]
                    }
                },
                setStateFromUrl: (_, { state }) => state.filters,
            },
        ],
        _graphsTab: [
            null as string | null,
            {
                setGraphsTab: (_, { tab }) => tab,
                setStateFromUrl: (_, { state }) => state.graphsTab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.graphsTab || oldTab,
            },
        ],
        _sourceTab: [
            null as string | null,
            {
                setSourceTab: (_, { tab }) => tab,
                setStateFromUrl: (_, { state }) => state.sourceTab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.sourceTab || oldTab,
            },
        ],
        _deviceTab: [
            null as string | null,
            {
                setDeviceTab: (_, { tab }) => tab,
                setStateFromUrl: (_, { state }) => state.deviceTab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.deviceTab || oldTab,
            },
        ],
        _pathTab: [
            null as string | null,
            {
                setPathTab: (_, { tab }) => tab,
                setStateFromUrl: (_, { state }) => state.pathTab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.pathTab || oldTab,
            },
        ],
        _geographyTab: [
            null as string | null,
            {
                setGeographyTab: (_, { tab }) => tab,
                setStateFromUrl: (_, { state }) => state.geographyTab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.geographyTab || oldTab,
            },
        ],
        isPathCleaningEnabled: [
            false as boolean,
            {
                setIsPathCleaningEnabled: (_, { isPathCleaningEnabled }) => isPathCleaningEnabled,
                setStateFromUrl: (_, { state }) => state.isPathCleaningEnabled || false,
            },
        ],
        _modalTileAndTab: [
            null as { tileId: TileId; tabId?: string } | null,
            {
                openModal: (_, { tileId, tabId }) => ({
                    tileId,
                    tabId,
                }),
                closeModal: () => null,
            },
        ],
        dateFilter: [
            {
                dateFrom: initialDateFrom,
                dateTo: initialDateTo,
                interval: initialInterval,
            },
            {
                setDates: (_, { dateTo, dateFrom }) => ({
                    dateTo,
                    dateFrom,
                    interval: getDefaultInterval(dateFrom, dateTo),
                }),
                setInterval: ({ dateFrom: oldDateFrom, dateTo: oldDateTo }, { interval }) => {
                    const { dateFrom, dateTo } = updateDatesWithInterval(interval, oldDateFrom, oldDateTo)
                    return {
                        dateTo,
                        dateFrom,
                        interval,
                    }
                },
                setStateFromUrl: (_, { state: { dateTo, dateFrom, interval } }) => {
                    if (!dateFrom && !dateTo) {
                        dateFrom = initialDateFrom
                        dateTo = initialDateTo
                    }
                    return {
                        dateTo,
                        dateFrom,
                        interval: interval || getDefaultInterval(dateFrom, dateTo),
                    }
                },
            },
        ],
    }),
    selectors(({ actions, values }) => ({
        graphsTab: [(s) => [s._graphsTab], (graphsTab: string | null) => graphsTab || GraphsTab.UNIQUE_USERS],
        sourceTab: [(s) => [s._sourceTab], (sourceTab: string | null) => sourceTab || SourceTab.REFERRING_DOMAIN],
        deviceTab: [(s) => [s._deviceTab], (deviceTab: string | null) => deviceTab || DeviceTab.DEVICE_TYPE],
        pathTab: [(s) => [s._pathTab], (pathTab: string | null) => pathTab || PathTab.PATH],
        geographyTab: [(s) => [s._geographyTab], (geographyTab: string | null) => geographyTab || GeographyTab.MAP],
        tiles: [
            (s) => [
                s.webAnalyticsFilters,
                s.graphsTab,
                s.sourceTab,
                s.deviceTab,
                s.pathTab,
                s.geographyTab,
                s.dateFilter,
                s.isPathCleaningEnabled,
                () => values.statusCheck,
                () => values.isGreaterThanMd,
                () => values.shouldShowGeographyTile,
            ],
            (
                webAnalyticsFilters,
                graphsTab,
                sourceTab,
                deviceTab,
                pathTab,
                geographyTab,
                { dateFrom, dateTo, interval },
                isPathCleaningEnabled: boolean,
                statusCheck,
                isGreaterThanMd: boolean,
                shouldShowGeographyTile
            ): WebDashboardTile[] => {
                const dateRange = {
                    date_from: dateFrom,
                    date_to: dateTo,
                }
                const compare = !!(dateRange.date_from && dateRange.date_to)

                const sampling = {
                    enabled: !!values.featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_SAMPLING],
                    forceSamplingRate: { numerator: 1, denominator: 10 },
                }

                const createInsightProps = (tile: TileId, tab?: string): InsightLogicProps => {
                    return {
                        dashboardItemId: getDashboardItemId(tile, tab, false),
                        loadPriority: loadPriorityMap[tile],
                    }
                }

                const allTiles: (WebDashboardTile | null)[] = [
                    {
                        tileId: TileId.OVERVIEW,
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                            orderWhenLargeClassName: 'xxl:order-0',
                        },
                        query: {
                            kind: NodeKind.WebOverviewQuery,
                            properties: webAnalyticsFilters,
                            dateRange,
                            sampling,
                        },
                        insightProps: createInsightProps(TileId.OVERVIEW),
                        canOpenModal: false,
                    },
                    {
                        tileId: TileId.GRAPHS,
                        layout: {
                            colSpanClassName: `md:col-span-2`,
                            orderWhenLargeClassName: 'xxl:order-1',
                        },
                        activeTabId: graphsTab,
                        setTabId: actions.setGraphsTab,
                        tabs: [
                            {
                                id: GraphsTab.UNIQUE_USERS,
                                title: 'Unique visitors',
                                linkText: 'Visitors',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        dateRange,
                                        interval,
                                        series: [
                                            {
                                                event: '$pageview',
                                                kind: NodeKind.EventsNode,
                                                math: BaseMathType.UniqueUsers,
                                                name: '$pageview',
                                                custom_name: 'Unique visitors',
                                            },
                                        ],
                                        trendsFilter: {
                                            compare,
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        filterTestAccounts: true,
                                        properties: webAnalyticsFilters,
                                    },
                                    hidePersonsModal: true,
                                    embedded: true,
                                },
                                showIntervalSelect: true,
                                insightProps: createInsightProps(TileId.GRAPHS, GraphsTab.UNIQUE_USERS),
                                canOpenInsight: true,
                            },
                            {
                                id: GraphsTab.PAGE_VIEWS,
                                title: 'Page views',
                                linkText: 'Views',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        dateRange,
                                        interval,
                                        series: [
                                            {
                                                event: '$pageview',
                                                kind: NodeKind.EventsNode,
                                                math: BaseMathType.TotalCount,
                                                name: '$pageview',
                                                custom_name: 'Page views',
                                            },
                                        ],
                                        trendsFilter: {
                                            compare,
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        filterTestAccounts: true,
                                        properties: webAnalyticsFilters,
                                    },
                                    hidePersonsModal: true,
                                    embedded: true,
                                },
                                showIntervalSelect: true,
                                insightProps: createInsightProps(TileId.GRAPHS, GraphsTab.PAGE_VIEWS),
                                canOpenInsight: true,
                            },
                            {
                                id: GraphsTab.NUM_SESSION,
                                title: 'Sessions',
                                linkText: 'Sessions',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        dateRange,
                                        interval,
                                        series: [
                                            {
                                                event: '$pageview',
                                                kind: NodeKind.EventsNode,
                                                math: BaseMathType.UniqueSessions,
                                                name: '$pageview',
                                                custom_name: 'Sessions',
                                            },
                                        ],
                                        trendsFilter: {
                                            compare,
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        filterTestAccounts: true,
                                        properties: webAnalyticsFilters,
                                    },
                                    suppressSessionAnalysisWarning: true,
                                    hidePersonsModal: true,
                                    embedded: true,
                                },
                                showIntervalSelect: true,
                                insightProps: createInsightProps(TileId.GRAPHS, GraphsTab.NUM_SESSION),
                                canOpenInsight: true,
                            },
                        ],
                    },
                    {
                        tileId: TileId.PATHS,
                        layout: {
                            colSpanClassName: `md:col-span-2`,
                            orderWhenLargeClassName: 'xxl:order-4',
                        },
                        activeTabId: pathTab,
                        setTabId: actions.setPathTab,
                        tabs: [
                            {
                                id: PathTab.PATH,
                                title: 'Top paths',
                                linkText: 'Path',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.Page,
                                        dateRange,
                                        includeScrollDepth: statusCheck?.isSendingPageLeavesScroll,
                                        includeBounceRate: true,
                                        sampling,
                                        doPathCleaning: isPathCleaningEnabled,
                                        limit: 10,
                                    },
                                    embedded: false,
                                },
                                insightProps: createInsightProps(TileId.PATHS, PathTab.PATH),
                                canOpenModal: true,
                                showPathCleaningControls: true,
                            },
                            {
                                id: PathTab.INITIAL_PATH,
                                title: 'Top entry paths',
                                linkText: 'Entry Path',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialPage,
                                        dateRange,
                                        includeScrollDepth: statusCheck?.isSendingPageLeavesScroll,
                                        sampling,
                                        doPathCleaning: isPathCleaningEnabled,
                                        limit: 10,
                                    },
                                    embedded: false,
                                },
                                insightProps: createInsightProps(TileId.PATHS, PathTab.INITIAL_PATH),
                                canOpenModal: true,
                                showPathCleaningControls: true,
                            },
                        ],
                    },
                    {
                        tileId: TileId.SOURCES,
                        layout: {
                            colSpanClassName: `md:col-span-1`,
                            orderWhenLargeClassName: 'xxl:order-2',
                        },
                        activeTabId: sourceTab,
                        setTabId: actions.setSourceTab,
                        tabs: [
                            {
                                id: SourceTab.REFERRING_DOMAIN,
                                title: 'Top referrers',
                                linkText: 'Referring domain',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialReferringDomain,
                                        dateRange,
                                        sampling,
                                        limit: 10,
                                    },
                                },
                                insightProps: createInsightProps(TileId.SOURCES, SourceTab.REFERRING_DOMAIN),
                                canOpenModal: true,
                            },
                            {
                                id: SourceTab.CHANNEL,
                                title: 'Top channels',
                                linkText: 'Channel',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialChannelType,
                                        dateRange,
                                        sampling,
                                        limit: 10,
                                    },
                                },
                                insightProps: createInsightProps(TileId.SOURCES, SourceTab.CHANNEL),
                                canOpenModal: true,
                            },
                            {
                                id: SourceTab.UTM_SOURCE,
                                title: 'Top sources',
                                linkText: 'UTM source',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialUTMSource,
                                        dateRange,
                                        sampling,
                                        limit: 10,
                                    },
                                },
                                insightProps: createInsightProps(TileId.SOURCES, SourceTab.UTM_SOURCE),
                                canOpenModal: true,
                            },
                            {
                                id: SourceTab.UTM_MEDIUM,
                                title: 'Top UTM medium',
                                linkText: 'UTM medium',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialUTMMedium,
                                        dateRange,
                                        sampling,
                                        limit: 10,
                                    },
                                },
                                insightProps: createInsightProps(TileId.SOURCES, SourceTab.UTM_MEDIUM),
                                canOpenModal: true,
                            },
                            {
                                id: SourceTab.UTM_CAMPAIGN,
                                title: 'Top UTM campaigns',
                                linkText: 'UTM campaign',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialUTMCampaign,
                                        dateRange,
                                        sampling,
                                        limit: 10,
                                    },
                                },
                                insightProps: createInsightProps(TileId.SOURCES, SourceTab.UTM_CAMPAIGN),
                                canOpenModal: true,
                            },
                            {
                                id: SourceTab.UTM_CONTENT,
                                title: 'Top UTM content',
                                linkText: 'UTM content',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialUTMContent,
                                        dateRange,
                                        sampling,
                                        limit: 10,
                                    },
                                },
                                insightProps: createInsightProps(TileId.SOURCES, SourceTab.UTM_CONTENT),
                                canOpenModal: true,
                            },
                            {
                                id: SourceTab.UTM_TERM,
                                title: 'Top UTM terms',
                                linkText: 'UTM term',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialUTMTerm,
                                        dateRange,
                                        sampling,
                                        limit: 10,
                                    },
                                },
                                insightProps: createInsightProps(TileId.SOURCES, SourceTab.UTM_TERM),
                                canOpenModal: true,
                            },
                        ],
                    },
                    {
                        tileId: TileId.DEVICES,
                        layout: {
                            colSpanClassName: `md:col-span-1`,
                            orderWhenLargeClassName: 'xxl:order-3',
                        },
                        activeTabId: deviceTab,
                        setTabId: actions.setDeviceTab,
                        tabs: [
                            {
                                id: DeviceTab.DEVICE_TYPE,
                                title: 'Device types',
                                linkText: 'Device type',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        breakdownFilter: { breakdown: '$device_type', breakdown_type: 'event' },
                                        dateRange,
                                        series: [
                                            {
                                                event: '$pageview',
                                                kind: NodeKind.EventsNode,
                                                math: BaseMathType.UniqueUsers,
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.ActionsPie,
                                            showLabelsOnSeries: true,
                                        },
                                        filterTestAccounts: true,
                                        properties: webAnalyticsFilters,
                                    },
                                    hidePersonsModal: true,
                                    vizSpecificOptions: {
                                        [ChartDisplayType.ActionsPie]: {
                                            disableHoverOffset: true,
                                            hideAggregation: true,
                                        },
                                    },
                                    embedded: true,
                                },
                                insightProps: createInsightProps(TileId.DEVICES, DeviceTab.DEVICE_TYPE),
                                canOpenInsight: true,
                            },
                            {
                                id: DeviceTab.BROWSER,
                                title: 'Top browsers',
                                linkText: 'Browser',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.Browser,
                                        dateRange,
                                        sampling,
                                    },
                                    embedded: false,
                                },
                                insightProps: createInsightProps(TileId.DEVICES, DeviceTab.BROWSER),
                                canOpenModal: true,
                            },
                            {
                                id: DeviceTab.OS,
                                title: 'Top OSs',
                                linkText: 'OS',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.OS,
                                        dateRange,
                                        sampling,
                                        limit: 10,
                                    },
                                    embedded: false,
                                },
                                insightProps: createInsightProps(TileId.DEVICES, DeviceTab.OS),
                                canOpenModal: true,
                            },
                        ],
                    },

                    shouldShowGeographyTile
                        ? {
                              tileId: TileId.GEOGRAPHY,
                              layout: {
                                  colSpanClassName: 'md:col-span-full',
                              },
                              activeTabId: geographyTab || GeographyTab.MAP,
                              setTabId: actions.setGeographyTab,
                              tabs: [
                                  {
                                      id: GeographyTab.MAP,
                                      title: 'World map',
                                      linkText: 'Map',
                                      query: {
                                          kind: NodeKind.InsightVizNode,
                                          source: {
                                              kind: NodeKind.TrendsQuery,
                                              breakdownFilter: {
                                                  breakdown: '$geoip_country_code',
                                                  breakdown_type: 'person',
                                              },
                                              dateRange,
                                              series: [
                                                  {
                                                      event: '$pageview',
                                                      kind: NodeKind.EventsNode,
                                                      math: BaseMathType.UniqueUsers,
                                                  },
                                              ],
                                              trendsFilter: {
                                                  display: ChartDisplayType.WorldMap,
                                              },
                                              filterTestAccounts: true,
                                              properties: webAnalyticsFilters,
                                          },
                                          hidePersonsModal: true,
                                          embedded: true,
                                      },
                                      insightProps: createInsightProps(TileId.GEOGRAPHY, GeographyTab.MAP),
                                      canOpenInsight: true,
                                  },
                                  {
                                      id: GeographyTab.COUNTRIES,
                                      title: 'Top countries',
                                      linkText: 'Countries',
                                      query: {
                                          full: true,
                                          kind: NodeKind.DataTableNode,
                                          source: {
                                              kind: NodeKind.WebStatsTableQuery,
                                              properties: webAnalyticsFilters,
                                              breakdownBy: WebStatsBreakdown.Country,
                                              dateRange,
                                              sampling,
                                              limit: 10,
                                          },
                                      },
                                      insightProps: createInsightProps(TileId.GEOGRAPHY, GeographyTab.COUNTRIES),
                                      canOpenModal: true,
                                  },
                                  {
                                      id: GeographyTab.REGIONS,
                                      title: 'Top regions',
                                      linkText: 'Regions',
                                      query: {
                                          full: true,
                                          kind: NodeKind.DataTableNode,
                                          source: {
                                              kind: NodeKind.WebStatsTableQuery,
                                              properties: webAnalyticsFilters,
                                              breakdownBy: WebStatsBreakdown.Region,
                                              dateRange,
                                              sampling,
                                              limit: 10,
                                          },
                                      },
                                      insightProps: createInsightProps(TileId.GEOGRAPHY, GeographyTab.REGIONS),
                                      canOpenModal: true,
                                  },
                                  {
                                      id: GeographyTab.CITIES,
                                      title: 'Top cities',
                                      linkText: 'Cities',
                                      query: {
                                          full: true,
                                          kind: NodeKind.DataTableNode,
                                          source: {
                                              kind: NodeKind.WebStatsTableQuery,
                                              properties: webAnalyticsFilters,
                                              breakdownBy: WebStatsBreakdown.City,
                                              dateRange,
                                              sampling,
                                              limit: 10,
                                          },
                                      },
                                      insightProps: createInsightProps(TileId.GEOGRAPHY, GeographyTab.CITIES),
                                      canOpenModal: true,
                                  },
                              ],
                          }
                        : null,
                    {
                        tileId: TileId.RETENTION,
                        title: 'Retention',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.RetentionQuery,
                                properties: webAnalyticsFilters,
                                dateRange,
                                filterTestAccounts: true,
                                retentionFilter: {
                                    retentionType: RETENTION_FIRST_TIME,
                                    retentionReference: 'total',
                                    totalIntervals: isGreaterThanMd ? 8 : 5,
                                    period: RetentionPeriod.Week,
                                },
                            },
                            vizSpecificOptions: {
                                [InsightType.RETENTION]: {
                                    hideLineGraph: true,
                                    hideSizeColumn: !isGreaterThanMd,
                                    useSmallLayout: !isGreaterThanMd,
                                },
                            },
                            embedded: true,
                        },
                        insightProps: createInsightProps(TileId.RETENTION),
                        canOpenInsight: true,
                        canOpenModal: false,
                    },
                ]
                return allTiles.filter(isNotNil)
            },
        ],
        modal: [
            (s) => [s.tiles, s._modalTileAndTab],
            (tiles, modalTileAndTab): WebDashboardModalQuery | null => {
                if (!modalTileAndTab) {
                    return null
                }
                const { tileId, tabId } = modalTileAndTab
                const tile = tiles.find((tile) => tile.tileId === tileId)
                if (!tile) {
                    throw new Error('Developer Error, tile not found')
                }

                const extendQuery = (query: QuerySchema): QuerySchema => {
                    if (query.kind === NodeKind.DataTableNode && query.source.kind === NodeKind.WebStatsTableQuery) {
                        return {
                            ...query,
                            source: {
                                ...query.source,
                                limit: 50,
                            },
                        }
                    } else {
                        return query
                    }
                }

                if (tabId) {
                    if (!('tabs' in tile)) {
                        throw new Error('Developer Error, tabId provided for non-tab tile')
                    }
                    const tab = tile.tabs.find((tab) => tab.id === tabId)
                    if (!tab) {
                        throw new Error('Developer Error, tab not found')
                    }
                    return {
                        tileId,
                        tabId,
                        title: tab.title,
                        showIntervalSelect: tab.showIntervalSelect,
                        insightProps: {
                            dashboardItemId: getDashboardItemId(tileId, tabId, true),
                            loadPriority: 0,
                        },
                        query: extendQuery(tab.query),
                        canOpenInsight: tab.canOpenInsight,
                    }
                } else {
                    if ('tabs' in tile) {
                        throw new Error('Developer Error, tabId not provided for tab tile')
                    }
                    return {
                        tileId,
                        title: tile.title,
                        insightProps: {
                            dashboardItemId: getDashboardItemId(tileId, undefined, true),
                            loadPriority: 0,
                        },
                        query: extendQuery(tile.query),
                    }
                }
            },
        ],
        hasCountryFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$geoip_country_code')
            },
        ],
        hasDeviceTypeFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$device_type')
            },
        ],
        hasBrowserFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$browser')
            },
        ],
        hasOSFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$os')
            },
        ],
        getNewInsightUrl: [
            (s) => [s.webAnalyticsFilters, s.dateFilter, s.tiles],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters, { dateTo, dateFrom }, tiles) => {
                return function getNewInsightUrl(tileId: TileId, tabId?: string): string {
                    const formatQueryForNewInsight = (query: QuerySchema): QuerySchema => {
                        if (query.kind === NodeKind.InsightVizNode) {
                            return {
                                ...query,
                                embedded: undefined,
                                hidePersonsModal: undefined,
                            }
                        }
                        return query
                    }

                    const tile = tiles.find((tile) => tile.tileId === tileId)
                    if (!tile) {
                        throw new Error('Developer Error, tile not found')
                    }
                    if (tabId) {
                        if (!('tabs' in tile)) {
                            throw new Error('Developer Error, tabId provided for non-tab tile')
                        }
                        const tab = tile.tabs.find((tab) => tab.id === tabId)
                        if (!tab) {
                            throw new Error('Developer Error, tab not found')
                        }
                        return urls.insightNew(
                            { properties: webAnalyticsFilters, date_from: dateFrom, date_to: dateTo },
                            null,
                            formatQueryForNewInsight(tab.query)
                        )
                    } else {
                        if ('tabs' in tile) {
                            throw new Error('Developer Error, tabId not provided for tab tile')
                        }
                        return urls.insightNew(
                            { properties: webAnalyticsFilters, date_from: dateFrom, date_to: dateTo },
                            null,
                            formatQueryForNewInsight(tile.query)
                        )
                    }
                }
            },
        ],
    })),
    loaders(() => ({
        // load the status check query here and pass the response into the component, so the response
        // is accessible in this logic
        statusCheck: {
            __default: null as WebAnalyticsStatusCheck | null,
            loadStatusCheck: async (): Promise<WebAnalyticsStatusCheck> => {
                const [pageviewResult, pageleaveResult, pageleaveScroll] = await Promise.allSettled([
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$pageview',
                    }),
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$pageleave',
                    }),
                    api.propertyDefinitions.list({
                        event_names: ['$pageleave'],
                        properties: ['$prev_pageview_max_content_percentage'],
                    }),
                ])

                // no need to worry about pagination here, event names beginning with $ are reserved, and we're not
                // going to add enough reserved event names that match this search term to cause problems
                const pageviewEntry =
                    pageviewResult.status === 'fulfilled'
                        ? pageviewResult.value.results.find((r) => r.name === '$pageview')
                        : undefined

                const pageleaveEntry =
                    pageleaveResult.status === 'fulfilled'
                        ? pageleaveResult.value.results.find((r) => r.name === '$pageleave')
                        : undefined

                const pageleaveScrollEntry =
                    pageleaveScroll.status === 'fulfilled'
                        ? pageleaveScroll.value.results.find((r) => r.name === '$prev_pageview_max_content_percentage')
                        : undefined

                const isSendingPageViews = !!pageviewEntry && !isDefinitionStale(pageviewEntry)
                const isSendingPageLeaves = !!pageleaveEntry && !isDefinitionStale(pageleaveEntry)
                const isSendingPageLeavesScroll = !!pageleaveScrollEntry && !isDefinitionStale(pageleaveScrollEntry)

                return {
                    isSendingPageViews,
                    isSendingPageLeaves,
                    isSendingPageLeavesScroll,
                }
            },
        },
        shouldShowGeographyTile: {
            _default: null as boolean | null,
            loadShouldShowGeographyTile: async (): Promise<boolean> => {
                const [propertiesResponse, pluginsResponse, pluginsConfigResponse] = await Promise.allSettled([
                    api.propertyDefinitions.list({
                        event_names: ['$pageview'],
                        properties: ['$geoip_country_code'],
                    }),
                    api.loadPaginatedResults('api/organizations/@current/plugins'),
                    api.loadPaginatedResults('api/plugin_config'),
                ])

                const hasNonStaleCountryCodeDefinition =
                    propertiesResponse.status === 'fulfilled' &&
                    propertiesResponse.value.results.some(
                        (property) => property.name === '$geoip_country_code' && !isDefinitionStale(property)
                    )

                if (!hasNonStaleCountryCodeDefinition) {
                    return false
                }

                const geoIpPlugin =
                    pluginsResponse.status === 'fulfilled' &&
                    pluginsResponse.value.find((plugin) => GEOIP_PLUGIN_URLS.includes(plugin.url))
                const geoIpPluginId = geoIpPlugin ? geoIpPlugin.id : undefined

                const geoIpPluginConfig =
                    isNotNil(geoIpPluginId) &&
                    pluginsConfigResponse.status === 'fulfilled' &&
                    pluginsConfigResponse.value.find((plugin) => plugin.plugin === geoIpPluginId)

                return !!geoIpPluginConfig && geoIpPluginConfig.enabled
            },
        },
    })),

    // start the loaders after mounting the logic
    afterMount(({ actions }) => {
        actions.loadStatusCheck()
        actions.loadShouldShowGeographyTile()
    }),
    windowValues({
        isGreaterThanMd: (window: Window) => window.innerWidth > 768,
    }),

    actionToUrl(({ values }) => {
        const stateToUrl = (): string => {
            const {
                webAnalyticsFilters,
                dateFilter: { dateTo, dateFrom, interval },
                sourceTab,
                deviceTab,
                pathTab,
                geographyTab,
                graphsTab,
                isPathCleaningEnabled,
            } = values

            const urlParams = new URLSearchParams()
            if (webAnalyticsFilters.length > 0) {
                urlParams.set('filters', JSON.stringify(webAnalyticsFilters))
            }
            if (dateFrom !== initialDateFrom || dateTo !== initialDateTo || interval !== initialInterval) {
                urlParams.set('date_from', dateFrom ?? '')
                urlParams.set('date_to', dateTo ?? '')
                urlParams.set('interval', interval ?? '')
            }
            if (deviceTab) {
                urlParams.set('device_tab', deviceTab)
            }
            if (sourceTab) {
                urlParams.set('source_tab', sourceTab)
            }
            if (graphsTab) {
                urlParams.set('graphs_tab', graphsTab)
            }
            if (pathTab) {
                urlParams.set('path_tab', pathTab)
            }
            if (geographyTab) {
                urlParams.set('geography_tab', geographyTab)
            }
            if (isPathCleaningEnabled) {
                urlParams.set('path_cleaning', isPathCleaningEnabled.toString())
            }
            return `/web?${urlParams.toString()}`
        }

        return {
            setWebAnalyticsFilters: stateToUrl,
            togglePropertyFilter: stateToUrl,
            setDates: stateToUrl,
            setInterval: stateToUrl,
            setDeviceTab: stateToUrl,
            setSourceTab: stateToUrl,
            setGraphsTab: stateToUrl,
            setPathTab: stateToUrl,
            setGeographyTab: stateToUrl,
        }
    }),

    urlToAction(({ actions }) => ({
        '/web': (
            _,
            {
                filters,
                date_from,
                date_to,
                interval,
                device_tab,
                source_tab,
                graphs_tab,
                path_tab,
                geography_tab,
                path_cleaning,
            }
        ) => {
            const parsedFilters = isWebAnalyticsPropertyFilters(filters) ? filters : initialWebAnalyticsFilter

            actions.setStateFromUrl({
                filters: parsedFilters,
                dateFrom: date_from || null,
                dateTo: date_to || null,
                interval: interval || null,
                deviceTab: device_tab || null,
                sourceTab: source_tab || null,
                graphsTab: graphs_tab || null,
                pathTab: path_tab || null,
                geographyTab: geography_tab || null,
                isPathCleaningEnabled: [true, 'true', 1, '1'].includes(path_cleaning),
            })
        },
    })),
])

const isDefinitionStale = (definition: EventDefinition | PropertyDefinition): boolean => {
    const parsedLastSeen = definition.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS
}
