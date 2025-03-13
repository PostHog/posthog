import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'

import { InsightVizNode, NodeKind, QuerySchema, TrendsQuery } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { BaseMathType, ChartDisplayType, InsightLogicProps, PropertyFilterType, PropertyOperator } from '~/types'

import type { pageReportsLogicType } from './pageReportsLogicType'
import {
    DeviceTab,
    GeographyTab,
    PathTab,
    SourceTab,
    TabsTile,
    TileId,
    TileVisualizationOption,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    webAnalyticsLogic,
    WebAnalyticsTile,
} from './webAnalyticsLogic'

// Define new TileIds for page reports to avoid conflicts with web analytics
export enum PageReportsTileId {
    // Path tiles
    ENTRY_PATHS = 'PAGE_REPORTS_ENTRY_PATHS',
    EXIT_PATHS = 'PAGE_REPORTS_EXIT_PATHS',
    OUTBOUND_CLICKS = 'PAGE_REPORTS_OUTBOUND_CLICKS',

    // Source tiles
    CHANNELS = 'PAGE_REPORTS_CHANNELS',
    REFERRERS = 'PAGE_REPORTS_REFERRERS',

    // Device tiles
    DEVICE_TYPES = 'PAGE_REPORTS_DEVICE_TYPES',
    BROWSERS = 'PAGE_REPORTS_BROWSERS',
    OPERATING_SYSTEMS = 'PAGE_REPORTS_OPERATING_SYSTEMS',

    // Geography tiles
    COUNTRIES = 'PAGE_REPORTS_COUNTRIES',
    REGIONS = 'PAGE_REPORTS_REGIONS',
    CITIES = 'PAGE_REPORTS_CITIES',
    TIMEZONES = 'PAGE_REPORTS_TIMEZONES',
    LANGUAGES = 'PAGE_REPORTS_LANGUAGES',
}

// Map PageReportsTileId to TileId and TabId for querying data
export const tileMapping: Record<PageReportsTileId, { tileId: TileId; tabId: string }> = {
    // Path tiles
    [PageReportsTileId.ENTRY_PATHS]: { tileId: TileId.PATHS, tabId: PathTab.INITIAL_PATH },
    [PageReportsTileId.EXIT_PATHS]: { tileId: TileId.PATHS, tabId: PathTab.END_PATH },
    [PageReportsTileId.OUTBOUND_CLICKS]: { tileId: TileId.PATHS, tabId: PathTab.EXIT_CLICK },

    // Source tiles
    [PageReportsTileId.CHANNELS]: { tileId: TileId.SOURCES, tabId: SourceTab.CHANNEL },
    [PageReportsTileId.REFERRERS]: { tileId: TileId.SOURCES, tabId: SourceTab.REFERRING_DOMAIN },

    // Device tiles
    [PageReportsTileId.DEVICE_TYPES]: { tileId: TileId.DEVICES, tabId: DeviceTab.DEVICE_TYPE },
    [PageReportsTileId.BROWSERS]: { tileId: TileId.DEVICES, tabId: DeviceTab.BROWSER },
    [PageReportsTileId.OPERATING_SYSTEMS]: { tileId: TileId.DEVICES, tabId: DeviceTab.OS },

    // Geography tiles
    [PageReportsTileId.COUNTRIES]: { tileId: TileId.GEOGRAPHY, tabId: GeographyTab.COUNTRIES },
    [PageReportsTileId.REGIONS]: { tileId: TileId.GEOGRAPHY, tabId: GeographyTab.REGIONS },
    [PageReportsTileId.CITIES]: { tileId: TileId.GEOGRAPHY, tabId: GeographyTab.CITIES },
    [PageReportsTileId.TIMEZONES]: { tileId: TileId.GEOGRAPHY, tabId: GeographyTab.TIMEZONES },
    [PageReportsTileId.LANGUAGES]: { tileId: TileId.GEOGRAPHY, tabId: GeographyTab.LANGUAGES },
}

export interface PageURL {
    url: string
    count: number
}

export interface PageReportsLogicProps {
    initialDateFrom?: string
    initialDateTo?: string
}

export const pageReportsLogic = kea<pageReportsLogicType>({
    path: ['scenes', 'web-analytics', 'pageReportsLogic'],
    props: {} as PageReportsLogicProps,

    connect: {
        values: [webAnalyticsLogic, ['tiles', 'shouldFilterTestAccounts']],
    },

    actions: () => ({
        setPageUrl: (url: string | string[] | null) => ({ url }),
        setPageUrlSearchTerm: (searchTerm: string) => ({ searchTerm }),
        loadPages: (searchTerm: string = '') => ({ searchTerm }),
        toggleStripQueryParams: () => ({}),
        setTileVisualization: (tileId: PageReportsTileId, visualization: TileVisualizationOption) => ({
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
            false as boolean,
            { persist: true },
            {
                toggleStripQueryParams: (state: boolean) => !state,
            },
        ],
        tileVisualizations: [
            {} as Record<PageReportsTileId, TileVisualizationOption>,
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
        pages: [
            [] as PageURL[],
            {
                loadPages: async ({ searchTerm }: { searchTerm: string }) => {
                    try {
                        let query: { kind: NodeKind; query: string }
                        // Simple query using the same pattern as heatmapsLogic
                        if (searchTerm) {
                            query = {
                                kind: NodeKind.HogQLQuery,
                                query: values.stripQueryParams
                                    ? hogql`SELECT DISTINCT cutQueryStringAndFragment(properties.$current_url) AS url, count() as count
                                        FROM events
                                        WHERE event = '$pageview'
                                        AND cutQueryStringAndFragment(properties.$current_url) like '%${hogql.identifier(
                                            searchTerm
                                        )}%'
                                        GROUP BY url
                                        ORDER BY count DESC
                                        LIMIT 100`
                                    : hogql`SELECT DISTINCT properties.$current_url AS url, count() as count
                                        FROM events
                                        WHERE event = '$pageview'
                                        AND properties.$current_url like '%${hogql.identifier(searchTerm)}%'
                                        GROUP BY url
                                        ORDER BY count DESC
                                        LIMIT 100`,
                            }
                        } else {
                            query = {
                                kind: NodeKind.HogQLQuery,
                                query: values.stripQueryParams
                                    ? hogql`SELECT DISTINCT cutQueryStringAndFragment(properties.$current_url) AS url, count() as count
                                        FROM events
                                        WHERE event = '$pageview'
                                        GROUP BY url
                                        ORDER BY count DESC
                                        LIMIT 100`
                                    : hogql`SELECT DISTINCT properties.$current_url AS url, count() as count
                                        FROM events
                                        WHERE event = '$pageview'
                                        GROUP BY url
                                        ORDER BY count DESC
                                        LIMIT 100`,
                            }
                        }

                        const response = await api.query(query)
                        const res = response as { results: [string, number][] }
                        const results = res.results?.map((x) => ({ url: x[0], count: x[1] })) as PageURL[]

                        return results
                    } catch (error) {
                        console.error('Error loading pages:', error)
                        return []
                    }
                },
            },
        ],
    }),

    selectors: {
        pageUrlSearchOptionsWithCount: [(selectors) => [selectors.pages], (pages: PageURL[]): PageURL[] => pages || []],
        hasPageUrl: [(selectors) => [selectors.pageUrl], (pageUrl: string | null) => !!pageUrl],
        isLoading: [
            (selectors) => [selectors.pagesLoading, selectors.isInitialLoad],
            (pagesLoading: boolean, isInitialLoad: boolean) => pagesLoading || isInitialLoad,
        ],
        pageUrlArray: [
            (selectors) => [selectors.pageUrl],
            (pageUrl: string | null): string[] => (pageUrl ? [pageUrl] : []),
        ],
        // Single queries selector that returns all queries
        queries: [
            (s) => [s.tiles],
            (tiles: WebAnalyticsTile[]) => {
                // Helper function to get query from a tile by tab ID so we
                // can use what we already have in the web analytics logic
                const getQuery = (tileId: TileId, tabId: string): QuerySchema | undefined => {
                    const tile = tiles?.find((t) => t.tileId === tileId) as TabsTile | undefined
                    return tile?.tabs.find((tab) => tab.id === tabId)?.query
                }

                // Return an object with all queries
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
        // Helper function for creating insight props
        createInsightProps: [
            () => [],
            () =>
                (tileId: TileId | PageReportsTileId, tabId?: string): InsightLogicProps => ({
                    dashboardItemId: `new-${tileId}${tabId ? `-${tabId}` : ''}`,
                    loadPriority: 0,
                    dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                }),
        ],
        // Combined metrics query - now accepts dateFilter and compareFilter as parameters
        combinedMetricsQuery: [
            (s) => [s.pageUrl, s.stripQueryParams, s.shouldFilterTestAccounts],
            (pageUrl: string | null, stripQueryParams: boolean, shouldFilterTestAccounts: boolean) =>
                (dateFilter: any, compareFilter: any): InsightVizNode<TrendsQuery> => ({
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
                        compareFilter,
                        filterTestAccounts: shouldFilterTestAccounts,
                        properties: pageUrl
                            ? [
                                  {
                                      key: '$current_url',
                                      // If stripQueryParams is true, we'll extract the base URL without query params
                                      value: pageUrl,
                                      operator: stripQueryParams ? PropertyOperator.IContains : PropertyOperator.Exact,
                                      type: PropertyFilterType.Event,
                                  },
                              ]
                            : [],
                    },
                    hidePersonsModal: true,
                    embedded: true,
                }),
        ],
        // Get visualization type for a specific tile
        getTileVisualization: [
            (s) => [s.tileVisualizations],
            (tileVisualizations: Record<PageReportsTileId, TileVisualizationOption>) =>
                (tileId: PageReportsTileId): TileVisualizationOption =>
                    tileVisualizations[tileId] || 'table',
        ],
        // Get query for a specific page reports tile
        getQueryForTile: [
            (s) => [s.queries],
            (queries: Record<string, QuerySchema | undefined>) =>
                (tileId: PageReportsTileId): QuerySchema | undefined => {
                    const mapping = tileMapping[tileId]
                    if (!mapping) {
                        return undefined
                    }

                    switch (tileId) {
                        case PageReportsTileId.ENTRY_PATHS:
                            return queries.entryPathsQuery
                        case PageReportsTileId.EXIT_PATHS:
                            return queries.exitPathsQuery
                        case PageReportsTileId.OUTBOUND_CLICKS:
                            return queries.outboundClicksQuery
                        case PageReportsTileId.CHANNELS:
                            return queries.channelsQuery
                        case PageReportsTileId.REFERRERS:
                            return queries.referrersQuery
                        case PageReportsTileId.DEVICE_TYPES:
                            return queries.deviceTypeQuery
                        case PageReportsTileId.BROWSERS:
                            return queries.browserQuery
                        case PageReportsTileId.OPERATING_SYSTEMS:
                            return queries.osQuery
                        case PageReportsTileId.COUNTRIES:
                            return queries.countriesQuery
                        case PageReportsTileId.REGIONS:
                            return queries.regionsQuery
                        case PageReportsTileId.CITIES:
                            return queries.citiesQuery
                        case PageReportsTileId.TIMEZONES:
                            return queries.timezonesQuery
                        case PageReportsTileId.LANGUAGES:
                            return queries.languagesQuery
                        default:
                            return undefined
                    }
                },
        ],
    },

    listeners: ({ actions, values }) => ({
        setPageUrlSearchTerm: ({ searchTerm }) => {
            actions.loadPages(searchTerm)
        },
        setPageUrl: ({ url }) => {
            // When URL changes, make sure we update the URL in the browser
            // This will trigger the actionToUrl handler
            router.actions.replace('/web/page-reports', url ? { pageURL: url } : {}, router.values.hashParams)
        },
        toggleStripQueryParams: () => {
            // Reload pages when the strip query params option changes
            actions.loadPages(values.pageUrlSearchTerm)
        },
        [webAnalyticsLogic.actionTypes.setDates]: () => {
            // Also reload pages when web analytics dates change
            actions.loadPages(values.pageUrlSearchTerm)
        },
    }),

    afterMount: ({ actions }: { actions: pageReportsLogicType['actions'] }) => {
        // Load pages immediately when component mounts
        actions.loadPages('')
    },

    urlToAction: ({ actions, values }) => ({
        '/web/page-reports': (_, searchParams) => {
            if (searchParams.pageURL && searchParams.pageURL !== values.pageUrl) {
                actions.setPageUrl(searchParams.pageURL)
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

            return ['/web/page-reports', searchParams, router.values.hashParams, { replace: true }]
        },
    }),
})
