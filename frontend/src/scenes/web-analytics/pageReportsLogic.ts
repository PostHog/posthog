import { kea } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    CompareFilter,
    DataVisualizationNode,
    HogQLQuery,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    TrendsQuery,
    WebAnalyticsPropertyFilters,
    WebPageURLSearchQuery,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    BaseMathType,
    ChartDisplayType,
    InsightLogicProps,
    IntervalType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

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
    parseWebAnalyticsURL,
} from './common'
import type { pageReportsLogicType } from './pageReportsLogicType'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export interface PageURLSearchResult {
    url: string
}

/**
 * Creates property filters for URL matching that handles query parameters consistently
 * Always attempts to parse full URLs into host+pathname filters to enable backend optimizations
 * @param url The URL to match
 * @param stripQueryParams Whether to strip query parameters (used as fallback for regex)
 * @returns An array of property filters for the URL
 */
export function createUrlPropertyFilter(url: string, stripQueryParams: boolean): WebAnalyticsPropertyFilters {
    // Always try to parse as full URL first - this enables pre-aggregated table optimizations on backend
    const parsed = parseWebAnalyticsURL(url)

    if (parsed.isValid && parsed.host && parsed.pathname) {
        return [
            {
                key: '$host',
                value: parsed.host,
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
            {
                key: '$pathname',
                value: parsed.pathname,
                operator: PropertyOperator.Exact,
                type: PropertyFilterType.Event,
            },
        ]
    }

    // Fallback to regex for partial URLs or unparseable input
    return [
        {
            key: '$current_url',
            value: stripQueryParams ? `^${url.split('?')[0]}(\\?.*)?$` : url,
            operator: stripQueryParams ? PropertyOperator.Regex : PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
    ]
}

const INTERVAL_FUNCTIONS: Record<IntervalType, string> = {
    second: 'toStartOfSecond',
    minute: 'toStartOfMinute',
    hour: 'toStartOfHour',
    day: 'toStartOfDay',
    week: 'toStartOfWeek',
    month: 'toStartOfMonth',
}

const getIntervalFunction = (interval: IntervalType): string => INTERVAL_FUNCTIONS[interval] ?? INTERVAL_FUNCTIONS.day

const createAvgTimeOnPageHogQLQuery = (
    host: string,
    pathname: string,
    filterTestAccounts: boolean,
    interval: IntervalType,
    dateRange: { date_from: string | null; date_to: string | null }
): HogQLQuery => {
    const intervalFn = getIntervalFunction(interval)
    return {
        kind: NodeKind.HogQLQuery,
        query: `
SELECT
    ${intervalFn}(ts) as period,
    avg(session_avg_duration) as avg_time_on_page
FROM (
    SELECT
        e.session.session_id as session_id,
        min(e.timestamp) as ts,
        avg(toFloat(e.properties.$prev_pageview_duration)) as session_avg_duration
    FROM events as e
    ANY LEFT JOIN events as prev
        ON e.properties.$prev_pageview_id = toString(prev.uuid)
    WHERE
        e.event IN ('$pageview', '$pageleave', '$screen')
        AND e.properties.$prev_pageview_pathname = {pathname}
        AND prev.properties.$host = {host}
    GROUP BY e.session.session_id
)
GROUP BY period
ORDER BY period`,
        filters: {
            filterTestAccounts,
            dateRange,
        },
        values: {
            pathname,
            host,
        },
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
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [webAnalyticsLogic, ['setDates']],
    },

    actions: () => ({
        setPageUrl: (url: string | string[] | null) => ({ url }),
        setPageUrlSearchTerm: (searchTerm: string) => ({ searchTerm }),
        loadPages: (searchTerm: string = '') => ({ searchTerm }),
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
                loadPagesUrlsSuccess: () => false,
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
                            stripQueryParams: true,
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
        stripQueryParams: [() => [], () => true],
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
                        utmSourceQuery: undefined,
                        utmMediumQuery: undefined,
                        utmCampaignQuery: undefined,
                        utmContentQuery: undefined,
                        utmTermQuery: undefined,
                        deviceTypeQuery: undefined,
                        browserQuery: undefined,
                        osQuery: undefined,
                        countriesQuery: undefined,
                        regionsQuery: undefined,
                        citiesQuery: undefined,
                        timezonesQuery: undefined,
                        languagesQuery: undefined,
                        topEventsQuery: undefined,
                        avgTimeOnPageTrendQuery: undefined,
                    }
                }

                const pageReportsPropertyFilters: WebAnalyticsPropertyFilters = [
                    ...createUrlPropertyFilter(pageUrl, stripQueryParams),
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
                            ...(pageUrl ? createUrlPropertyFilter(pageUrl, stripQueryParams) : []),
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

                const parsedUrl = parseWebAnalyticsURL(pageUrl)
                const avgTimeOnPageTrendQuery: DataVisualizationNode | undefined =
                    parsedUrl.isValid && parsedUrl.host && parsedUrl.pathname
                        ? {
                              kind: NodeKind.DataVisualizationNode,
                              source: createAvgTimeOnPageHogQLQuery(
                                  parsedUrl.host,
                                  parsedUrl.pathname,
                                  shouldFilterTestAccounts,
                                  dateFilter.interval,
                                  dateRange
                              ),
                              display: ChartDisplayType.ActionsLineGraph,
                              chartSettings: {
                                  xAxis: { column: 'period' },
                                  yAxis: [
                                      {
                                          column: 'avg_time_on_page',
                                          settings: {
                                              display: { label: 'Average time' },
                                              formatting: { suffix: ' seconds', decimalPlaces: 2 },
                                          },
                                      },
                                  ],
                              },
                          }
                        : undefined

                return {
                    // Path queries
                    entryPathsQuery: getQuery(TileId.PATHS, PathTab.INITIAL_PATH),
                    exitPathsQuery: getQuery(TileId.PATHS, PathTab.END_PATH),
                    outboundClicksQuery: getQuery(TileId.PATHS, PathTab.EXIT_CLICK),
                    prevPathsQuery,

                    // Source queries
                    channelsQuery: getQuery(TileId.SOURCES, SourceTab.CHANNEL),
                    referrersQuery: getQuery(TileId.SOURCES, SourceTab.REFERRING_DOMAIN),
                    utmSourceQuery: getQuery(TileId.SOURCES, SourceTab.UTM_SOURCE),
                    utmMediumQuery: getQuery(TileId.SOURCES, SourceTab.UTM_MEDIUM),
                    utmCampaignQuery: getQuery(TileId.SOURCES, SourceTab.UTM_CAMPAIGN),
                    utmContentQuery: getQuery(TileId.SOURCES, SourceTab.UTM_CONTENT),
                    utmTermQuery: getQuery(TileId.SOURCES, SourceTab.UTM_TERM),

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
                    avgTimeOnPageTrendQuery,
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
                        properties: pageUrl ? createUrlPropertyFilter(pageUrl, stripQueryParams) : [],
                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                    embedded: true,
                }),
        ],
        tiles: [
            (s) => [s.queries, s.pageUrl, s.createInsightProps, s.combinedMetricsQuery, s.dateFilter, s.featureFlags],
            (
                queries: Record<string, QuerySchema | undefined>,
                pageUrl: string | null,
                createInsightProps: (tileId: TileId, tabId?: string) => InsightLogicProps,
                combinedMetricsQuery: (
                    dateFilter: typeof webAnalyticsLogic.values.dateFilter
                ) => InsightVizNode<TrendsQuery>,
                dateFilter: typeof webAnalyticsLogic.values.dateFilter,
                featureFlags: Record<string, boolean | string>
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
                            queries.avgTimeOnPageTrendQuery &&
                            featureFlags[FEATURE_FLAGS.PAGE_REPORTS_AVERAGE_PAGE_VIEW]
                                ? {
                                      kind: 'query',
                                      tileId: TileId.PAGE_REPORTS_AVG_TIME_ON_PAGE_TREND,
                                      title: 'Average time on page',
                                      query: queries.avgTimeOnPageTrendQuery,
                                      insightProps: createInsightProps(TileId.PAGE_REPORTS_AVG_TIME_ON_PAGE_TREND),
                                      layout: {
                                          className: 'w-full min-h-[300px]',
                                      },
                                      docs: {
                                          title: 'Average time on page',
                                          description: 'Average time visitors spend on this page',
                                      },
                                      canOpenModal: false,
                                  }
                                : null,
                        ].filter(Boolean) as WebAnalyticsTile[],
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
                                TileId.PAGE_REPORTS_PREVIOUS_PAGE,
                                'Previous Pages',
                                'Pages users visited before this page. For internal navigation, we used the previous pathname. If the user arrived from an external link, we used the referrer URL.',
                                queries.prevPathsQuery
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
                                TileId.PAGE_REPORTS_OUTBOUND_CLICKS,
                                'Outbound Clicks',
                                'External links users click on this page',
                                queries.outboundClicksQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_UTM_SOURCE,
                                'UTM Source',
                                'UTM source parameter showing the source of traffic to this page',
                                queries.utmSourceQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_UTM_MEDIUM,
                                'UTM Medium',
                                'UTM medium parameter showing the marketing medium that brought users to this page',
                                queries.utmMediumQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_UTM_CAMPAIGN,
                                'UTM Campaign',
                                'UTM campaign parameter showing the marketing campaign that brought users to this page',
                                queries.utmCampaignQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_UTM_CONTENT,
                                'UTM Content',
                                'UTM content parameter showing which specific link or content brought users to this page',
                                queries.utmContentQuery
                            ),
                            createQueryTile(
                                TileId.PAGE_REPORTS_UTM_TERM,
                                'UTM Term',
                                'UTM term parameter showing the keywords associated with traffic to this page',
                                queries.utmTermQuery
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

    listeners: ({ actions }) => ({
        setPageUrlSearchTerm: ({ searchTerm }) => {
            actions.loadPages(searchTerm)
        },
        setPageUrl: ({ url }) => {
            router.actions.replace('/web/page-reports', url ? { pageURL: url } : {}, router.values.hashParams)
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
