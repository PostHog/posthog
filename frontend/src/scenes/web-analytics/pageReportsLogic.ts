import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
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
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    webAnalyticsLogic,
    WebAnalyticsTile,
} from './webAnalyticsLogic'

export interface PageURL {
    url: string
    count: number
}

export interface PageReportsLogicProps {}

export const pageReportsLogic = kea<pageReportsLogicType>({
    path: ['scenes', 'web-analytics', 'pageReportsLogic'],
    props: {} as PageReportsLogicProps,

    connect: {
        values: [webAnalyticsLogic, ['dateFilter', 'tiles', 'shouldFilterTestAccounts', 'compareFilter']],
        actions: [webAnalyticsLogic, ['togglePropertyFilter']],
    },

    actions: () => ({
        setPageUrl: (url: string | string[] | null) => ({ url }),
        setPageUrlSearchTerm: (searchTerm: string) => ({ searchTerm }),
        loadPages: (searchTerm: string = '') => ({ searchTerm }),
        toggleStripQueryParams: () => ({}),
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
                // Find tiles by ID
                const pathsTile = tiles?.find((tile: WebAnalyticsTile) => tile.tileId === TileId.PATHS) as
                    | TabsTile
                    | undefined
                const sourcesTile = tiles?.find((tile: WebAnalyticsTile) => tile.tileId === TileId.SOURCES) as
                    | TabsTile
                    | undefined
                const devicesTile = tiles?.find((tile: WebAnalyticsTile) => tile.tileId === TileId.DEVICES) as
                    | TabsTile
                    | undefined
                const geographyTile = tiles?.find((tile: WebAnalyticsTile) => tile.tileId === TileId.GEOGRAPHY) as
                    | TabsTile
                    | undefined

                // Return an object with all queries
                return {
                    // Path queries
                    entryPathsQuery: pathsTile?.tabs.find((tab) => tab.id === PathTab.INITIAL_PATH)?.query,
                    exitPathsQuery: pathsTile?.tabs.find((tab) => tab.id === PathTab.END_PATH)?.query,
                    outboundClicksQuery: pathsTile?.tabs.find((tab) => tab.id === PathTab.EXIT_CLICK)?.query,

                    // Source queries
                    channelsQuery: sourcesTile?.tabs.find((tab) => tab.id === SourceTab.CHANNEL)?.query,
                    referrersQuery: sourcesTile?.tabs.find((tab) => tab.id === SourceTab.REFERRING_DOMAIN)?.query,

                    // Device queries
                    deviceTypeQuery: devicesTile?.tabs.find((tab) => tab.id === DeviceTab.DEVICE_TYPE)?.query,
                    browserQuery: devicesTile?.tabs.find((tab) => tab.id === DeviceTab.BROWSER)?.query,
                    osQuery: devicesTile?.tabs.find((tab) => tab.id === DeviceTab.OS)?.query,

                    // Geography queries
                    countriesQuery: geographyTile?.tabs.find((tab) => tab.id === GeographyTab.COUNTRIES)?.query,
                    regionsQuery: geographyTile?.tabs.find((tab) => tab.id === GeographyTab.REGIONS)?.query,
                    citiesQuery: geographyTile?.tabs.find((tab) => tab.id === GeographyTab.CITIES)?.query,
                    timezonesQuery: geographyTile?.tabs.find((tab) => tab.id === GeographyTab.TIMEZONES)?.query,
                    languagesQuery: geographyTile?.tabs.find((tab) => tab.id === GeographyTab.LANGUAGES)?.query,
                }
            },
        ],
        // Helper function for creating insight props
        createInsightProps: [
            () => [],
            () =>
                (tileId: TileId, tabId?: string): InsightLogicProps => ({
                    dashboardItemId: `new-${tileId}${tabId ? `-${tabId}` : ''}`,
                    loadPriority: 0,
                    dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                }),
        ],
        // Combined metrics query
        combinedMetricsQuery: [
            (s) => [s.pageUrl, s.stripQueryParams, s.dateFilter, s.compareFilter, s.shouldFilterTestAccounts],
            (
                pageUrl: string | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: any,
                shouldFilterTestAccounts: boolean
            ): InsightVizNode<TrendsQuery> => ({
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
                    properties: [
                        {
                            key: stripQueryParams
                                ? 'cutQueryStringAndFragment(properties.$current_url)'
                                : '$current_url',
                            value: pageUrl,
                            // Use IContains when stripQueryParams is active to group URLs
                            operator: stripQueryParams
                                ? PropertyOperator.IContains
                                : PropertyOperator.IsCleanedPathExact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                },
                hidePersonsModal: true,
                embedded: true,
            }),
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

            // Apply or remove the filter when pageUrl changes
            const stripQueryParams = values.stripQueryParams
            const key = stripQueryParams ? 'cutQueryStringAndFragment(properties.$current_url)' : '$current_url'

            // Call the connected action directly
            const urlValue = Array.isArray(url) ? (url.length > 0 ? url[0] : '') : url || ''
            actions.togglePropertyFilter(PropertyFilterType.Event, key, urlValue)
        },
        toggleStripQueryParams: () => {
            // Reload pages when the strip query params option changes
            actions.loadPages(values.pageUrlSearchTerm)

            // Update the property filter with the new key and operator
            const stripQueryParams = values.stripQueryParams
            const key = stripQueryParams ? 'cutQueryStringAndFragment(properties.$current_url)' : '$current_url'

            // Call the connected action directly
            actions.togglePropertyFilter(PropertyFilterType.Event, key, values.pageUrl || '')
        },
        [webAnalyticsLogic.actionTypes.setDates]: () => {
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
