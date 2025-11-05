import { kea } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'

import {
    CompareFilter,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    TrendsQuery,
    WebAnalyticsPropertyFilter,
    WebAnalyticsPropertyFilters,
    WebPageURLSearchQuery,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { BaseMathType, ChartDisplayType, InsightLogicProps, PropertyFilterType, PropertyOperator } from '~/types'

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
    WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
    WebAnalyticsTile,
    WebTileLayout,
} from './common'
import type { pageReportsLogicType } from './pageReportsLogicType'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export interface PageURLSearchResult {
    url: string
    count: number
}

/**
 * Creates a property filter for URL matching that handles query parameters consistently
 * @param url The URL to match
 * @param stripQueryParams Whether to strip query parameters
 * @returns A property filter object for the URL
 */
export function createUrlPropertyFilter(url: string, stripQueryParams: boolean): WebAnalyticsPropertyFilter {
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
        values: [
            webAnalyticsLogic,
            [
                'tiles as webAnalyticsTiles',
                'shouldFilterTestAccounts',
                'dateFilter',
                'compareFilter',
                'webAnalyticsFilters',
                'isPathCleaningEnabled',
            ],
        ],
        actions: [webAnalyticsLogic, ['setDates']],
    },

    actions: () => ({
        setPageUrl: (url: string | string[] | null) => ({ url }),
        setPageUrlSearchTerm: (searchTerm: string) => ({ searchTerm }),
        loadPages: (searchTerm: string = '') => ({ searchTerm }),
        toggleStripQueryParams: () => ({}),
        setTileVisualization: (tileId: TileId, visualization: TileVisualizationOption) => ({
            tileId,
            visualization,
        }),
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
    }),

    loaders: ({ values }) => ({
        pagesUrls: [
            [] as PageURLSearchResult[],
            {
                loadPagesUrls: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    await breakpoint(100) // debounce the typing
                    const response = await api.query<WebPageURLSearchQuery>(
                        setLatestVersionsOnQuery({
                            kind: NodeKind.WebPageURLSearchQuery,
                            searchTerm: searchTerm,
                            stripQueryParams: values.stripQueryParams,
                            dateRange: {
                                date_from: values.dateFilter.dateFrom,
                                date_to: values.dateFilter.dateTo,
                            },
                            properties: [],
                        })
                    )
                    breakpoint() // ensure that if more typing has happened since we sent the request, we don't update the state
                    return response.results
                },
            },
        ],
    }),

    selectors: {
        hasPageUrl: [(selectors) => [selectors.pageUrl], (pageUrl: string | null) => !!pageUrl],
        isLoading: [
            (selectors) => [selectors.pagesUrlsLoading, selectors.isInitialLoad],
            (pagesUrlsLoading: boolean, isInitialLoad: boolean) => pagesUrlsLoading || isInitialLoad,
        ],
        queries: [
            (s) => [
                s.webAnalyticsTiles,
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.compareFilter,
                s.isPathCleaningEnabled,
            ],
            (
                webAnalyticsTiles: WebAnalyticsTile[],
                pageUrl: string | null,
                stripQueryParams: boolean,
                dateFilter: typeof webAnalyticsLogic.values.dateFilter,
                shouldFilterTestAccounts: boolean,
                compareFilter: CompareFilter,
                isPathCleaningEnabled: boolean
            ) => {
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
                        topEventsQuery: undefined,
                    }
                }

                const pageReportsPropertyFilters: WebAnalyticsPropertyFilters = [
                    createUrlPropertyFilter(pageUrl, stripQueryParams),
                ]
                const dateRange = { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo }

                // Helper function to get query from a tile by tab ID
                const getQuery = (tileId: TileId, tabId: string): QuerySchema | undefined => {
                    const tile = webAnalyticsTiles?.find((t) => t.tileId === tileId) as TabsTile | undefined
                    const query = tile?.tabs.find((tab) => tab.id === tabId)?.query

                    if (query && 'source' in query && query.source) {
                        const modifiedQuery = JSON.parse(JSON.stringify(query))

                        // Find and update the $current_url property filter
                        if (modifiedQuery.source.properties) {
                            modifiedQuery.source.properties = pageReportsPropertyFilters
                        }

                        return modifiedQuery
                    }

                    return query
                }

                // Enforcing the type to be QuerySchema so we can build it in a type-safe way
                const getTopEventsQuery = (): QuerySchema | undefined => ({
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                event: null,
                                name: 'All events',
                                math: BaseMathType.TotalCount,
                            },
                        ],
                        trendsFilter: {},
                        breakdownFilter: {
                            breakdowns: [
                                {
                                    property: 'event',
                                    type: 'event_metadata',
                                },
                            ],
                        },
                        properties: [
                            ...(pageUrl ? [createUrlPropertyFilter(pageUrl, stripQueryParams)] : []),
                            {
                                key: 'event',
                                value: ['$pageview', '$pageleave'],
                                operator: PropertyOperator.IsNot,
                                type: PropertyFilterType.EventMetadata,
                            },
                        ],
                        filterTestAccounts: shouldFilterTestAccounts,
                        dateRange,
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                    embedded: true,
                    hidePersonsModal: true,
                })

                const prevPathsQuery = {
                    full: true,
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        breakdownBy: WebStatsBreakdown.PreviousPage,
                        dateRange,
                        filterTestAccounts: shouldFilterTestAccounts,
                        properties: pageReportsPropertyFilters,
                        compareFilter,
                        limit: 10,
                        doPathCleaning: isPathCleaningEnabled,
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                    embedded: true,
                    showActions: true,
                }

                return {
                    // Path queries
                    entryPathsQuery: getQuery(TileId.PATHS, PathTab.INITIAL_PATH),
                    exitPathsQuery: getQuery(TileId.PATHS, PathTab.END_PATH),
                    outboundClicksQuery: getQuery(TileId.PATHS, PathTab.EXIT_CLICK),
                    prevPathsQuery,

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

                    topEventsQuery: getTopEventsQuery(),
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
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
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
                        canOpenModal: true,
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
                            className: 'grid grid-cols-1 md:grid-cols-3 gap-4 mb-8',
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
                            createQueryTile(
                                TileId.PAGE_REPORTS_PREVIOUS_PAGE,
                                'Previous Pages',
                                'Pages users visited before this page. For internal navigation, we used the previous pathname. If the user arrived from an external link, we used the referrer URL.',
                                queries.prevPathsQuery
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
                    {
                        kind: 'section',
                        tileId: TileId.PAGE_REPORTS_TOP_EVENTS_SECTION,
                        title: '',
                        layout: {
                            className: 'grid-cols-1 gap-2',
                        },
                        tiles: [
                            createQueryTile(
                                TileId.PAGE_REPORTS_TOP_EVENTS,
                                'Top Events',
                                'Most common events triggered by users on this page, broken down by event type',
                                queries.topEventsQuery,
                                {
                                    className: 'w-full min-h-[300px]',
                                }
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
        },
        toggleStripQueryParams: () => {
            actions.loadPages(values.pageUrlSearchTerm)
        },
        loadPages: ({ searchTerm }) => {
            actions.loadPagesUrls({ searchTerm })
        },
    }),

    afterMount: ({ actions }: { actions: pageReportsLogicType['actions'] }) => {
        actions.loadPages('')
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
