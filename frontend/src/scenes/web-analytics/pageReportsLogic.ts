import { kea } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isValidRegexp } from 'lib/utils/regexp'
import { teamLogic } from 'scenes/teamLogic'

import {
    CompareFilter,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    TrendsQuery,
    WebAnalyticsPropertyFilters,
    WebPageURLSearchQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import {
    BaseMathType,
    ChartDisplayType,
    InsightLogicProps,
    IntervalType,
    PathCleaningFilter,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
    TeamPublicType,
    TeamType,
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
    eventPropertiesToPathClean,
    parseWebAnalyticsURL,
} from './common'
import { PROPERTY_PATHNAME } from './constants'
import type { pageReportsLogicType } from './pageReportsLogicType'
import { webAnalyticsLogic } from './webAnalyticsLogic'

/**
 * Creates property filters for URL matching that handles query parameters consistently
 * Always attempts to parse full URLs into host+pathname filters to enable backend optimizations
 * @param url The URL to match
 * @param stripQueryParams Whether to strip query parameters (used as fallback for regex)
 * @returns An array of property filters for the URL
 */
export interface PageURLSearchResult {
    url: string
}

export function createUrlPropertyFilter(url: string, stripQueryParams: boolean): WebAnalyticsPropertyFilters {
    // kea-router JSON-parses query params (?pageURL=123 arrives as a number) and pageUrl is
    // persisted, so a non-string value would otherwise crash `url.split` below on every recompute
    const urlString: string = typeof url === 'string' ? url : String(url ?? '')
    const parsed = parseWebAnalyticsURL(urlString)

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
            value: stripQueryParams ? `^${urlString.split('?')[0]}(\\?.*)?$` : urlString,
            operator: stripQueryParams ? PropertyOperator.Regex : PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
    ]
}

function safeDecode(value: string): string {
    try {
        return decodeURIComponent(value)
    } catch {
        return value
    }
}

export function applyPathCleaningToFilters(
    filters: WebAnalyticsPropertyFilters,
    isPathCleaningEnabled: boolean
): WebAnalyticsPropertyFilters {
    if (!isPathCleaningEnabled) {
        return filters
    }
    return filters.map((filter) => {
        if (
            filter.type === PropertyFilterType.Event &&
            filter.operator === PropertyOperator.Exact &&
            typeof filter.key === 'string' &&
            eventPropertiesToPathClean.has(filter.key)
        ) {
            return {
                ...filter,
                operator: PropertyOperator.IsCleanedPathExact,
                // decode because `new URL()` percent-encodes cleaning aliases (`<id>` → `%3Cid%3E`), which never match
                value: typeof filter.value === 'string' ? safeDecode(filter.value) : filter.value,
            }
        }
        return filter
    })
}

export function cleanPathnameForDisplay(pathname: string, filters: PathCleaningFilter[]): string {
    return filters.reduce((cleaned, filter) => {
        if (!filter.regex || !isValidRegexp(filter.regex)) {
            return cleaned
        }
        return cleaned.replace(new RegExp(filter.regex, 'gi'), filter.alias ?? '')
    }, pathname)
}

export function cleanPageURLForDisplay(url: string, filters: PathCleaningFilter[]): string {
    if (filters.length === 0) {
        return url
    }
    const parsed = parseWebAnalyticsURL(url)
    if (parsed.isValid && parsed.pathname) {
        const cleanedPathname = cleanPathnameForDisplay(parsed.pathname, filters)
        return parsed.host ? `${parsed.host}${cleanedPathname}` : cleanedPathname
    }
    return cleanPathnameForDisplay(url, filters)
}

export interface PageURLOption {
    key: string
    label: string
}

export function buildPageUrlOptions(
    pagesUrls: PageURLSearchResult[],
    pageUrl: string | null,
    filters: PathCleaningFilter[],
    isPathCleaningEnabled: boolean
): PageURLOption[] {
    if (!isPathCleaningEnabled || filters.length === 0) {
        return pagesUrls.map(({ url }) => ({ key: url, label: url }))
    }

    const representativeByCleaned = new Map<string, string>()
    if (typeof pageUrl === 'string' && pageUrl) {
        representativeByCleaned.set(cleanPageURLForDisplay(pageUrl, filters), pageUrl)
    }
    for (const { url } of pagesUrls) {
        const cleaned = cleanPageURLForDisplay(url, filters)
        if (!representativeByCleaned.has(cleaned)) {
            representativeByCleaned.set(cleaned, url)
        }
    }

    return [...representativeByCleaned.entries()].map(([label, key]) => ({ key, label }))
}

function createHostFilter(host: string | null): WebAnalyticsPropertyFilters {
    return host ? [{ type: PropertyFilterType.Event, key: '$host', operator: PropertyOperator.Exact, value: host }] : []
}

/**
 * Builds the property filters for a page report: the page URL filter, with the selected host (when
 * set) taking precedence over the host embedded in the URL. This lets the host dropdown re-scope every
 * report tile — e.g. comparing the same pathname across different domains — instead of leaving the
 * tiles pinned to the host baked into the picked URL.
 */
export function createPageReportsFilters(
    url: string,
    stripQueryParams: boolean,
    selectedHost: string | null,
    isPathCleaningEnabled: boolean = false
): WebAnalyticsPropertyFilters {
    const filters = createUrlPropertyFilter(url, stripQueryParams)

    // Drop the URL's own host so the explicitly selected host wins, then apply it.
    const withSelectedHost = selectedHost
        ? [...filters.filter((filter) => filter.key !== '$host'), ...createHostFilter(selectedHost)]
        : filters

    return applyPathCleaningToFilters(withSelectedHost, isPathCleaningEnabled)
}

const createTimeOnPageTrendsQuery = (
    pathname: string,
    filterTestAccounts: boolean,
    interval: IntervalType,
    dateRange: { date_from: string | null; date_to: string | null },
    isPathCleaningEnabled: boolean
): InsightVizNode<TrendsQuery> => {
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    math: PropertyMathType.P90,
                    math_property: '$prev_pageview_duration',
                    properties: [
                        {
                            type: PropertyFilterType.EventMetadata,
                            key: 'event',
                            operator: PropertyOperator.In,
                            value: ['$pageview', '$pageleave', '$screen'],
                        },
                        {
                            type: PropertyFilterType.Event,
                            key: '$prev_pageview_pathname',
                            operator: isPathCleaningEnabled
                                ? PropertyOperator.IsCleanedPathExact
                                : PropertyOperator.Exact,
                            value: isPathCleaningEnabled ? safeDecode(pathname) : pathname,
                        },
                        {
                            type: PropertyFilterType.Event,
                            key: '$prev_pageview_duration',
                            operator: PropertyOperator.IsSet,
                            value: PropertyOperator.IsSet,
                        },
                    ],
                },
            ],
            interval,
            dateRange: { date_from: dateRange.date_from, date_to: dateRange.date_to },
            filterTestAccounts,
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                aggregationAxisFormat: 'duration',
            },
        },
        embedded: true,
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
                'selectedHost',
                'controls',
            ],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [webAnalyticsLogic, ['setDates', 'setDomainFilter', 'setIsPathCleaningEnabled']],
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
                    const dateRange = {
                        date_from: values.dateFilter.dateFrom,
                        date_to: values.dateFilter.dateTo,
                    }

                    const hostFilter = createHostFilter(values.selectedHost)

                    if (values.featureFlags[FEATURE_FLAGS.PAGE_REPORTS_RANKED_URL_SEARCH]) {
                        const properties: WebAnalyticsPropertyFilters = [...hostFilter]
                        if (searchTerm) {
                            properties.push({
                                type: PropertyFilterType.Event,
                                key: PROPERTY_PATHNAME,
                                operator: PropertyOperator.IContains,
                                value: searchTerm,
                            })
                        }

                        const response = await api.query<WebStatsTableQuery>(
                            setLatestVersionsOnQuery({
                                kind: NodeKind.WebStatsTableQuery,
                                breakdownBy: WebStatsBreakdown.Page,
                                includeHost: true,
                                // Serve the unfiltered URL list from the paths lazy-precompute
                                // instead of a multi-second live scan. The precompute eligibility
                                // gate requires includeBounceRate, so request it even though the
                                // picker only reads the path column (the URL set/order is unchanged).
                                // A search term adds a pathname filter, which the gate rejects, so
                                // those queries stay on the live path. Reuse the dashboard's resolved
                                // tri-state so an explicit user opt-out in the menu is honored here too.
                                includeBounceRate: true,
                                useWebAnalyticsPrecompute: values.controls.useWebAnalyticsPrecompute,
                                dateRange,
                                properties,
                                limit: 100,
                                doPathCleaning: values.isPathCleaningEnabled,
                                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                            })
                        )
                        breakpoint()
                        return (response.results ?? []).flatMap((row): PageURLSearchResult[] => {
                            const url = Array.isArray(row) ? row[0] : null
                            return typeof url === 'string' && url ? [{ url }] : []
                        })
                    }

                    const response = await api.query<WebPageURLSearchQuery>(
                        setLatestVersionsOnQuery({
                            kind: NodeKind.WebPageURLSearchQuery,
                            searchTerm: searchTerm,
                            stripQueryParams: true,
                            dateRange,
                            properties: hostFilter,
                            tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
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
        pathCleaningFilters: [
            (s) => [s.currentTeam],
            (currentTeam: TeamType | TeamPublicType | null): PathCleaningFilter[] =>
                (currentTeam && 'path_cleaning_filters' in currentTeam ? currentTeam.path_cleaning_filters : null) ??
                [],
        ],
        pageUrlOptions: [
            (s) => [s.pagesUrls, s.pageUrl, s.pathCleaningFilters, s.isPathCleaningEnabled],
            (
                pagesUrls: PageURLSearchResult[],
                pageUrl: string | null,
                pathCleaningFilters: PathCleaningFilter[],
                isPathCleaningEnabled: boolean
            ): PageURLOption[] => buildPageUrlOptions(pagesUrls, pageUrl, pathCleaningFilters, isPathCleaningEnabled),
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
                s.selectedHost,
            ],
            (
                webAnalyticsTiles: WebAnalyticsTile[],
                pageUrl: string | null,
                stripQueryParams: boolean,
                dateFilter: typeof webAnalyticsLogic.values.dateFilter,
                shouldFilterTestAccounts: boolean,
                compareFilter: CompareFilter,
                isPathCleaningEnabled: boolean,
                selectedHost: string | null
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

                const pageReportsPropertyFilters: WebAnalyticsPropertyFilters = createPageReportsFilters(
                    pageUrl,
                    stripQueryParams,
                    selectedHost,
                    isPathCleaningEnabled
                )
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
                            ...pageReportsPropertyFilters,
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
                const avgTimeOnPageTrendQuery: InsightVizNode<TrendsQuery> | undefined =
                    parsedUrl.isValid && parsedUrl.host && parsedUrl.pathname
                        ? createTimeOnPageTrendsQuery(
                              parsedUrl.pathname,
                              shouldFilterTestAccounts,
                              dateFilter.interval,
                              dateRange,
                              isPathCleaningEnabled
                          )
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
                    dashboardItemId: `new-AdHoc.${tileId}${tabId ? `-${tabId}` : ''}`,
                    loadPriority: 0,
                    dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                }),
        ],
        combinedMetricsQuery: [
            (s) => [s.pageUrl, s.stripQueryParams, s.shouldFilterTestAccounts, s.selectedHost, s.isPathCleaningEnabled],
            (
                pageUrl: string | null,
                stripQueryParams: boolean,
                shouldFilterTestAccounts: boolean,
                selectedHost: string | null,
                isPathCleaningEnabled: boolean
            ) =>
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
                        properties: pageUrl
                            ? createPageReportsFilters(pageUrl, stripQueryParams, selectedHost, isPathCleaningEnabled)
                            : [],
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
                        canOpenInsight: true,
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
                                canOpenInsight: true,
                            },
                            queries.avgTimeOnPageTrendQuery &&
                            featureFlags[FEATURE_FLAGS.PAGE_REPORTS_AVERAGE_PAGE_VIEW]
                                ? {
                                      kind: 'query',
                                      tileId: TileId.PAGE_REPORTS_AVG_TIME_ON_PAGE_TREND,
                                      title: 'Time on page',
                                      query: queries.avgTimeOnPageTrendQuery,
                                      insightProps: createInsightProps(TileId.PAGE_REPORTS_AVG_TIME_ON_PAGE_TREND),
                                      layout: {
                                          className: 'w-full min-h-[300px]',
                                      },
                                      docs: {
                                          title: 'Time on page',
                                          description: 'The 90th percentile of time users spent on this page.',
                                      },
                                      canOpenModal: false,
                                      canOpenInsight: true,
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

    listeners: ({ actions, values }) => ({
        setPageUrlSearchTerm: ({ searchTerm }) => {
            actions.loadPages(searchTerm)
        },
        setPageUrl: ({ url }) => {
            router.actions.replace('/web/page-reports', url ? { pageURL: url } : {}, router.values.hashParams)
        },
        loadPages: ({ searchTerm }) => {
            actions.loadPagesUrls({ searchTerm })
        },
        setDates: () => {
            if (values.featureFlags[FEATURE_FLAGS.PAGE_REPORTS_RANKED_URL_SEARCH]) {
                actions.loadPages(values.pageUrlSearchTerm)
            }
        },
        setDomainFilter: () => {
            actions.loadPages(values.pageUrlSearchTerm)
        },
        setIsPathCleaningEnabled: () => {
            actions.loadPages(values.pageUrlSearchTerm)
        },
    }),

    afterMount: ({ actions }: { actions: pageReportsLogicType['actions'] }) => {
        actions.loadPages('')
    },

    urlToAction: ({ actions, values }) => ({
        '/web/page-reports': (_, searchParams) => {
            // kea-router JSON-parses query params, so ?pageURL=123 arrives as a number
            const pageURL = searchParams.pageURL == null ? null : String(searchParams.pageURL)
            if (pageURL && pageURL !== values.pageUrl) {
                actions.setPageUrl(pageURL)
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
