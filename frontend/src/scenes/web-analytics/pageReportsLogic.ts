import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'

import { InsightVizNode, NodeKind, QuerySchema, TrendsQuery } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
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
    SourceTab,
    TabsTile,
    TileId,
    TileVisualizationOption,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    webAnalyticsLogic,
    WebAnalyticsTile,
} from './webAnalyticsLogic'

export interface PageURL {
    url: string
    count: number
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
        values: [webAnalyticsLogic, ['tiles', 'shouldFilterTestAccounts']],
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
        queries: [
            (s) => [s.tiles, s.pageUrl, s.stripQueryParams],
            (tiles: WebAnalyticsTile[], pageUrl: string | null, stripQueryParams: boolean) => {
                // Helper function to get query from a tile by tab ID so we
                // can use what we already have in the web analytics logic
                const getQuery = (tileId: TileId, tabId: string): QuerySchema | undefined => {
                    const tile = tiles?.find((t) => t.tileId === tileId) as TabsTile | undefined
                    const query = tile?.tabs.find((tab) => tab.id === tabId)?.query

                    // If we have a query and a pageUrl, we need to modify the query to filter by URL
                    if (query && pageUrl) {
                        // Deep clone the query to avoid modifying the original
                        const modifiedQuery = JSON.parse(JSON.stringify(query))

                        // Handle different query types
                        if ('source' in modifiedQuery) {
                            const source = modifiedQuery.source

                            // For WebStatsTableQuery type (most common)
                            if (source && 'kind' in source && source.kind === NodeKind.WebStatsTableQuery) {
                                source.properties = [createUrlPropertyFilter(pageUrl, stripQueryParams)]
                            }

                            // For DataTableNode type (used in some geography queries)
                            else if (source && 'kind' in source && source.kind === NodeKind.DataTableNode) {
                                if (source.source && typeof source.source === 'object') {
                                    if ('properties' in source.source) {
                                        source.source.properties = [createUrlPropertyFilter(pageUrl, stripQueryParams)]
                                    }
                                }
                            }

                            // For ActionsNode or EventsNode (used in some queries)
                            else if (
                                source &&
                                'kind' in source &&
                                (source.kind === NodeKind.ActionsNode || source.kind === NodeKind.EventsNode)
                            ) {
                                source.properties = [createUrlPropertyFilter(pageUrl, stripQueryParams)]
                            }

                            // For HogQLQuery (used in some custom queries)
                            else if (source && 'kind' in source && source.kind === NodeKind.HogQLQuery) {
                                // HogQL queries might need special handling depending on their structure
                                if ('properties' in source) {
                                    source.properties = [createUrlPropertyFilter(pageUrl, stripQueryParams)]
                                }
                            }

                            // For any other query type with properties at the source level
                            else if (source && 'properties' in source) {
                                source.properties = [createUrlPropertyFilter(pageUrl, stripQueryParams)]
                            }
                        }

                        return modifiedQuery
                    }

                    return query
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
                        properties: pageUrl ? [createUrlPropertyFilter(pageUrl, stripQueryParams)] : [],
                    },
                    hidePersonsModal: true,
                    embedded: true,
                }),
        ],
        getQueryForTile: [
            (s) => [s.queries],
            (queries: Record<string, QuerySchema | undefined>) =>
                (tileId: TileId): QuerySchema | undefined => {
                    switch (tileId) {
                        case TileId.PAGE_REPORTS_ENTRY_PATHS:
                            return queries.entryPathsQuery
                        case TileId.PAGE_REPORTS_EXIT_PATHS:
                            return queries.exitPathsQuery
                        case TileId.PAGE_REPORTS_OUTBOUND_CLICKS:
                            return queries.outboundClicksQuery
                        case TileId.PAGE_REPORTS_CHANNELS:
                            return queries.channelsQuery
                        case TileId.PAGE_REPORTS_REFERRERS:
                            return queries.referrersQuery
                        case TileId.PAGE_REPORTS_DEVICE_TYPES:
                            return queries.deviceTypeQuery
                        case TileId.PAGE_REPORTS_BROWSERS:
                            return queries.browserQuery
                        case TileId.PAGE_REPORTS_OPERATING_SYSTEMS:
                            return queries.osQuery
                        case TileId.PAGE_REPORTS_COUNTRIES:
                            return queries.countriesQuery
                        case TileId.PAGE_REPORTS_REGIONS:
                            return queries.regionsQuery
                        case TileId.PAGE_REPORTS_CITIES:
                            return queries.citiesQuery
                        case TileId.PAGE_REPORTS_TIMEZONES:
                            return queries.timezonesQuery
                        case TileId.PAGE_REPORTS_LANGUAGES:
                            return queries.languagesQuery
                        default:
                            return undefined
                    }
                },
        ],
        // Debug selector to help troubleshoot query structures
        debugQueryStructure: [
            (s) => [s.queries],
            (queries: Record<string, QuerySchema | undefined>) => {
                // This selector can be used in development to inspect query structures
                // Just add a console.log statement in a component to see the structure
                return {
                    outboundClicksStructure: queries.outboundClicksQuery
                        ? JSON.stringify(queries.outboundClicksQuery, null, 2)
                        : 'No query',
                    countriesStructure: queries.countriesQuery
                        ? JSON.stringify(queries.countriesQuery, null, 2)
                        : 'No query',
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
