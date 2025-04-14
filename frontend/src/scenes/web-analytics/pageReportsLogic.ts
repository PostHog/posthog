import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'

import {
    InsightVizNode,
    NodeKind,
    QuerySchema,
    TrendsQuery,
    WebOverviewQueryResponse,
    WebPageURLSearchQuery,
} from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    InsightLogicProps,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import type { pageReportsLogicType } from './pageReportsLogicType'
import {
    DeviceTab,
    GeographyTab,
    PathTab,
    SectionTile,
    SourceTab,
    TabsTile,
    TileId,
    TileVisualizationOption,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    webAnalyticsLogic,
    WebAnalyticsTile,
    WebTileLayout,
} from './webAnalyticsLogic'

export interface PageURLSearchResult {
    url: string
    count: number
}

// Define interface for page stats
export interface PageStats {
    pageviews: number
    visitors: number
    recordings: number
    clicks: number
    rageClicks: number
    deadClicks: number
    errors: number
    surveysShown: number
    surveysAnswered: number
    sessions: number
    sessionDuration: number
    bounceRate: number
    isLoading: boolean
}

interface WebOverviewStats {
    pageviews: number
    visitors: number
    recordings: number
    clicks: number
    rageClicks: number
    deadClicks: number
    errors: number
    surveysShown: number
    surveysAnswered: number
    sessions: number
    sessionDuration: number
    bounceRate: number
    isLoading: boolean
}

/**
 * Creates a property filter for URL matching that handles query parameters consistently
 * @param url The URL to match
 * @param stripQueryParams Whether to strip query parameters
 * @returns A property filter object for the URL
 */
export function createUrlPropertyFilter(url: string, stripQueryParams: boolean): AnyPropertyFilter {
    return {
        key: '$current_url',
        value: stripQueryParams ? `^${url.split('?')[0]}(\\?.*)?$` : url,
        operator: stripQueryParams ? PropertyOperator.Regex : PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    }
}

export const pageReportsLogic = kea<pageReportsLogicType>({
    path: ['scenes', 'web-analytics', 'pageReportsLogic'],

    connect: {
        values: [webAnalyticsLogic, ['tiles as webAnalyticsTiles', 'shouldFilterTestAccounts', 'dateFilter']],
        actions: [webAnalyticsLogic, ['setDates']],
    },

    actions: () => ({
        setPageUrl: (url: string | string[] | null) => ({ url }),
        setPageUrlSearchTerm: (searchTerm: string) => ({ searchTerm }),
        loadPages: (searchTerm: string = '') => {
            return { searchTerm }
        },
        toggleStripQueryParams: () => ({}),
        setTileVisualization: (tileId: TileId, visualization: TileVisualizationOption) => ({
            tileId,
            visualization,
        }),
        loadPageStats: (pageUrl: string | null) => ({ pageUrl }),
    }),

    reducers: () => ({
        pageUrl: [
            null as string | null,
            { persist: true },
            {
                setPageUrl: (_state, { url }) => {
                    if (Array.isArray(url)) {
                        // We're querying by url and count()
                        return url.length > 0 ? url[0] : null
                    }
                    return url
                },
            },
        ],
        pageUrlSearchTerm: [
            '',
            {
                setPageUrlSearchTerm: (_state, { searchTerm }) => searchTerm,
            },
        ],
        isInitialLoad: [
            true,
            {
                loadPagesSuccess: () => false,
            },
        ],
        stripQueryParams: [
            true,
            { persist: true },
            {
                toggleStripQueryParams: (state: boolean) => !state,
            },
        ],
        tileVisualizations: [
            {} as Record<TileId, TileVisualizationOption>,
            { persist: true },
            {
                setTileVisualization: (state, { tileId, visualization }) => ({
                    ...state,
                    [tileId]: visualization,
                }),
            },
        ],
        pageStats: [
            {
                pageviews: 0,
                visitors: 0,
                recordings: 0,
                clicks: 0,
                rageClicks: 0,
                deadClicks: 0,
                errors: 0,
                surveysShown: 0,
                surveysAnswered: 0,
                sessions: 0,
                sessionDuration: 0,
                bounceRate: 0,
                isLoading: true,
            } as PageStats,
            {
                loadPageStats: (state) => ({ ...state, isLoading: true }),
                loadPageStatsSuccess: (_, { stats }) => ({
                    pageviews: stats?.pageviews ?? 0,
                    visitors: stats?.visitors ?? 0,
                    recordings: stats?.recordings ?? 0,
                    clicks: stats?.clicks ?? 0,
                    rageClicks: stats?.rageClicks ?? 0,
                    deadClicks: stats?.deadClicks ?? 0,
                    errors: stats?.errors ?? 0,
                    surveysShown: stats?.surveysShown ?? 0,
                    surveysAnswered: stats?.surveysAnswered ?? 0,
                    sessions: stats?.sessions ?? 0,
                    sessionDuration: stats?.sessionDuration ?? 0,
                    bounceRate: stats?.bounceRate ?? 0,
                    isLoading: false,
                }),
                loadPageStatsFailure: (state) => ({ ...state, isLoading: false }),
            },
        ],
    }),

    loaders: ({ values }) => ({
        pagesUrls: [
            [] as PageURLSearchResult[],
            {
                loadPagesUrls: async ({ searchTerm }: { searchTerm: string }) => {
                    try {
                        const response = await api.query<WebPageURLSearchQuery>({
                            kind: NodeKind.WebPageURLSearchQuery,
                            searchTerm: searchTerm,
                            stripQueryParams: values.stripQueryParams,
                            dateRange: {
                                date_from: values.dateFilter.dateFrom,
                                date_to: values.dateFilter.dateTo,
                            },
                            properties: [],
                        })

                        return response.results
                    } catch (error) {
                        console.error('Error loading pages:', error)
                        return []
                    }
                },
            },
        ],
        stats: [
            null as WebOverviewStats | null,
            {
                loadPageStats: async ({ pageUrl }: { pageUrl: string | null }) => {
                    try {
                        if (!pageUrl) {
                            return null
                        }

                        // Use the web overview query with extended stats
                        const query = {
                            kind: NodeKind.WebOverviewQuery,
                            dateRange: { date_from: '-7d', date_to: null },
                            properties: [createUrlPropertyFilter(pageUrl, values.stripQueryParams)],
                            includeExtendedStats: true,
                        }

                        const response = (await api.query(query)) as WebOverviewQueryResponse

                        // Convert array of metrics to object format
                        const findMetricValue = (key: string): number => {
                            const metric = response.results?.find((r) => r.key === key)
                            return metric?.value ?? 0
                        }

                        return {
                            pageviews: findMetricValue('views'),
                            visitors: findMetricValue('visitors'),
                            recordings: findMetricValue('recordings'),
                            clicks: findMetricValue('clicks'),
                            rageClicks: findMetricValue('rage clicks'),
                            deadClicks: findMetricValue('dead clicks'),
                            errors: findMetricValue('errors'),
                            surveysShown: findMetricValue('surveys shown'),
                            surveysAnswered: findMetricValue('surveys answered'),
                            sessions: findMetricValue('sessions'),
                            sessionDuration: findMetricValue('session duration'),
                            bounceRate: findMetricValue('bounce rate') / 100, // Convert from percentage back to decimal
                            isLoading: false,
                        }
                    } catch (error) {
                        console.error('Error loading page stats:', error)
                        return null
                    }
                },
            },
        ],
    }),

    selectors: {
        hasPageUrl: [(selectors) => [selectors.pageUrl], (pageUrl: string | null) => !!pageUrl],
        isLoading: [
            (selectors) => [selectors.pagesUrlsLoading, selectors.isInitialLoad, selectors.pageStats],
            (pagesUrlsLoading: boolean, isInitialLoad: boolean, pageStats: PageStats) =>
                pagesUrlsLoading || isInitialLoad || pageStats.isLoading,
        ],
        queries: [
            (s) => [s.webAnalyticsTiles, s.pageUrl, s.stripQueryParams],
            (webAnalyticsTiles: WebAnalyticsTile[], pageUrl: string | null, stripQueryParams: boolean) => {
                // If we don't have a pageUrl, return empty queries to rendering problems
                if (!pageUrl) {
                    return {
                        entryPathsQuery: undefined,
                        exitPathsQuery: undefined,
                        outboundClicksQuery: undefined,
                        channelsQuery: undefined,
                        referrersQuery: undefined,
                        deviceTypeQuery: undefined,
                        browserQuery: undefined,
                        osQuery: undefined,
                        countriesQuery: undefined,
                        regionsQuery: undefined,
                        citiesQuery: undefined,
                        timezonesQuery: undefined,
                        languagesQuery: undefined,
                    }
                }

                // Helper function to get query from a tile by tab ID
                const getQuery = (tileId: TileId, tabId: string): QuerySchema | undefined => {
                    const tile = webAnalyticsTiles?.find((t) => t.tileId === tileId) as TabsTile | undefined
                    const query = tile?.tabs.find((tab) => tab.id === tabId)?.query

                    if (query && 'source' in query && query.source) {
                        const modifiedQuery = JSON.parse(JSON.stringify(query))

                        // Find and update the $current_url property filter
                        if (modifiedQuery.source.properties) {
                            modifiedQuery.source.properties = [createUrlPropertyFilter(pageUrl, stripQueryParams)]
                        }

                        return modifiedQuery
                    }

                    return query
                }

                return {
                    // Path queries
                    entryPathsQuery: getQuery(TileId.PATHS, PathTab.INITIAL_PATH),
                    exitPathsQuery: getQuery(TileId.PATHS, PathTab.END_PATH),
                    outboundClicksQuery: getQuery(TileId.PATHS, PathTab.EXIT_CLICK),

                    // Source queries
                    channelsQuery: getQuery(TileId.SOURCES, SourceTab.CHANNEL),
                    referrersQuery: getQuery(TileId.SOURCES, SourceTab.REFERRING_DOMAIN),

                    // Device queries
                    deviceTypeQuery: getQuery(TileId.DEVICES, DeviceTab.DEVICE_TYPE),
                    browserQuery: getQuery(TileId.DEVICES, DeviceTab.BROWSER),
                    osQuery: getQuery(TileId.DEVICES, DeviceTab.OS),

                    // Geography queries
                    countriesQuery: getQuery(TileId.GEOGRAPHY, GeographyTab.COUNTRIES),
                    regionsQuery: getQuery(TileId.GEOGRAPHY, GeographyTab.REGIONS),
                    citiesQuery: getQuery(TileId.GEOGRAPHY, GeographyTab.CITIES),
                    timezonesQuery: getQuery(TileId.GEOGRAPHY, GeographyTab.TIMEZONES),
                    languagesQuery: getQuery(TileId.GEOGRAPHY, GeographyTab.LANGUAGES),
                }
            },
        ],
        createInsightProps: [
            () => [],
            () =>
                (tileId: TileId, tabId?: string): InsightLogicProps => ({
                    dashboardItemId: `new-${tileId}${tabId ? `-${tabId}` : ''}`,
                    loadPriority: 0,
                    dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                }),
        ],
        combinedMetricsQuery: [
            (s) => [s.pageUrl, s.stripQueryParams, s.shouldFilterTestAccounts],
            (pageUrl: string | null, stripQueryParams: boolean, shouldFilterTestAccounts: boolean) =>
                (dateFilter: typeof webAnalyticsLogic.values.dateFilter): InsightVizNode<TrendsQuery> => ({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$pageview',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                                name: '$pageview',
                                custom_name: 'Unique visitors',
                            },
                            {
                                event: '$pageview',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.TotalCount,
                                name: '$pageview',
                                custom_name: 'Page views',
                            },
                            {
                                event: '$pageview',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueSessions,
                                name: '$pageview',
                                custom_name: 'Sessions',
                            },
                        ],
                        interval: dateFilter.interval,
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        trendsFilter: {
                            display: ChartDisplayType.ActionsLineGraph,
                            showLegend: true,
                        },
                        filterTestAccounts: shouldFilterTestAccounts,
                        properties: pageUrl ? [createUrlPropertyFilter(pageUrl, stripQueryParams)] : [],
                    },
                    hidePersonsModal: true,
                    embedded: true,
                }),
        ],
        tiles: [
            (s) => [s.queries, s.pageUrl, s.createInsightProps, s.combinedMetricsQuery, s.dateFilter],
            (
                queries: Record<string, QuerySchema | undefined>,
                pageUrl: string | null,
                createInsightProps: (tileId: TileId, tabId?: string) => InsightLogicProps,
                combinedMetricsQuery: (
                    dateFilter: typeof webAnalyticsLogic.values.dateFilter
                ) => InsightVizNode<TrendsQuery>,
                dateFilter: typeof webAnalyticsLogic.values.dateFilter
            ): SectionTile[] => {
                if (!pageUrl) {
                    return []
                }

                const createQueryTile = (
                    tileId: TileId,
                    title: string,
                    description: string,
                    query: QuerySchema | undefined,
                    layout?: WebTileLayout
                ): WebAnalyticsTile | null => {
                    if (!query) {
                        return null
                    }

                    return {
                        kind: 'query',
                        tileId,
                        title,
                        query,
                        showIntervalSelect: false,
                        insightProps: createInsightProps(tileId),
                        layout: layout ?? {
                            className: 'flex flex-col h-full min-h-[400px]',
                        },
                        docs: {
                            title,
                            description,
                        },
                    }
                }

                return [
                    {
                        kind: 'section',
                        tileId: TileId.PAGE_REPORTS_COMBINED_METRICS_CHART,
                        tiles: [
                            {
                                kind: 'query',
                                tileId: TileId.PAGE_REPORTS_COMBINED_METRICS_CHART,
                                title: 'Trends over time',
                                query: combinedMetricsQuery(dateFilter),
                                showIntervalSelect: true,
                                insightProps: createInsightProps(
                                    TileId.PAGE_REPORTS_COMBINED_METRICS_CHART,
                                    'combined'
                                ),
                                layout: {
                                    className: 'w-full min-h-[350px]',
                                },
                                docs: {
                                    title: 'Trends over time',
                                    description: 'Key metrics for this page over time',
                                },
                            },
                        ],
                        layout: {
                            className: 'w-full',
                        },
                    },
                    {
                        kind: 'section',
                        tileId: TileId.PAGE_REPORTS_PATHS_SECTION,
                        layout: {
                            className: 'grid grid-cols-1 md:grid-cols-3 gap-4 mb-8',
                        },
                        tiles: [
                            createQueryTile(
                                TileId.PAGE_REPORTS_ENTRY_PATHS,
                                'Entry Paths',
                                'How users arrive at this page',
                                queries.entryPathsQuery,
                                {
                                    className: 'flex flex-col h-full min-h-[400px]',
                                }
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_EXIT_PATHS,
                                'Exit Paths',
                                'Where users go after viewing this page',
                                queries.exitPathsQuery,
                                {
                                    className: 'flex flex-col h-full min-h-[400px]',
                                }
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_OUTBOUND_CLICKS,
                                'Outbound Clicks',
                                'External links users click on this page',
                                queries.outboundClicksQuery
                            ),
                        ].filter(Boolean) as WebAnalyticsTile[],
                    },
                    {
                        kind: 'section',
                        tileId: TileId.PAGE_REPORTS_TRAFFIC_SECTION,
                        layout: {
                            className: 'grid grid-cols-1 md:grid-cols-2 gap-4 mb-8',
                        },
                        tiles: [
                            createQueryTile(
                                TileId.PAGE_REPORTS_CHANNELS,
                                'Channels',
                                'Marketing channels bringing users to this page',
                                queries.channelsQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_REFERRERS,
                                'Referrers',
                                'Websites referring traffic to this page',
                                queries.referrersQuery
                            ),
                        ].filter(Boolean) as WebAnalyticsTile[],
                    },
                    {
                        kind: 'section',
                        tileId: TileId.PAGE_REPORTS_DEVICE_INFORMATION_SECTION,
                        layout: {
                            className: 'grid grid-cols-1 md:grid-cols-3 gap-4 mb-8',
                        },
                        tiles: [
                            createQueryTile(
                                TileId.PAGE_REPORTS_DEVICE_TYPES,
                                'Device Types',
                                'Types of devices used to access this page',
                                queries.deviceTypeQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_BROWSERS,
                                'Browsers',
                                'Browsers used to access this page',
                                queries.browserQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_OPERATING_SYSTEMS,
                                'Operating Systems',
                                'Operating systems used to access this page',
                                queries.osQuery
                            ),
                        ].filter(Boolean) as WebAnalyticsTile[],
                    },
                    {
                        kind: 'section',
                        tileId: TileId.PAGE_REPORTS_GEOGRAPHY_SECTION,
                        layout: {
                            className: 'grid grid-cols-1 md:grid-cols-3 gap-4 mb-8',
                        },
                        tiles: [
                            createQueryTile(
                                TileId.PAGE_REPORTS_COUNTRIES,
                                'Countries',
                                'Countries where users access this page from',
                                queries.countriesQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_REGIONS,
                                'Regions',
                                'Regions where users access this page from',
                                queries.regionsQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_CITIES,
                                'Cities',
                                'Cities where users access this page from',
                                queries.citiesQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_TIMEZONES,
                                'Timezones',
                                'Timezones where users access this page from',
                                queries.timezonesQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_LANGUAGES,
                                'Languages',
                                'Languages of users accessing this page',
                                queries.languagesQuery
                            ),
                        ].filter(Boolean) as WebAnalyticsTile[],
                    },
                ]
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        setPageUrlSearchTerm: ({ searchTerm }) => {
            actions.loadPages(searchTerm)
        },
        setPageUrl: ({ url }) => {
            router.actions.replace('/web/page-reports', url ? { pageURL: url } : {}, router.values.hashParams)
            if (url) {
                actions.loadPageStats(url as string)
            }
        },
        toggleStripQueryParams: () => {
            actions.loadPages(values.pageUrlSearchTerm)
            if (values.pageUrl) {
                actions.loadPageStats(values.pageUrl)
            }
        },
        loadPages: ({ searchTerm }) => {
            actions.loadPagesUrls({ searchTerm })
        },
    }),

    afterMount: ({
        actions,
        values,
    }: {
        actions: pageReportsLogicType['actions']
        values: pageReportsLogicType['values']
    }) => {
        actions.loadPages('')
        if (values.pageUrl) {
            actions.loadPageStats(values.pageUrl)
        }
    },

    urlToAction: ({ actions, values }) => ({
        '/web/page-reports': (_, searchParams) => {
            if (searchParams.pageURL && searchParams.pageURL !== values.pageUrl) {
                actions.setPageUrl(searchParams.pageURL)
            }

            // Only toggle stripQueryParams if it's explicitly present in the URL
            if ('stripQueryParams' in searchParams && !!searchParams.stripQueryParams !== values.stripQueryParams) {
                actions.toggleStripQueryParams()
            }
        },
    }),

    actionToUrl: ({ values }) => ({
        setPageUrl: () => {
            const searchParams = { ...router.values.searchParams }

            if (values.pageUrl) {
                searchParams.pageURL = values.pageUrl
            } else {
                delete searchParams.pageURL
            }

            // Only include stripQueryParams if it's different from the URL
            if (!!router.values.searchParams.stripQueryParams !== values.stripQueryParams) {
                searchParams.stripQueryParams = values.stripQueryParams
            }

            return ['/web/page-reports', searchParams, router.values.hashParams, { replace: true }]
        },
        toggleStripQueryParams: () => {
            const searchParams = { ...router.values.searchParams }
            searchParams.stripQueryParams = values.stripQueryParams

            return ['/web/page-reports', searchParams, router.values.hashParams, { replace: true }]
        },
    }),
})
