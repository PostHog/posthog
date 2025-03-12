import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { getDefaultInterval, updateDatesWithInterval } from 'lib/utils'

import { performQuery } from '~/queries/query'
import { BreakdownFilter, InsightVizNode, NodeKind, WebStatsBreakdown } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { ChartDisplayType, PropertyFilterType, PropertyOperator } from '~/types'

export enum PageReportsTileId {
    PAGES = 'pages',
    PATHS = 'paths',
    SOURCES = 'sources',
    DEVICES = 'devices',
    GEOGRAPHY = 'geography',
    WEBSITE_ENGAGEMENT = 'engagement',
}

export interface PageURL {
    url: string
    url_matching: 'exact' | 'contains' | 'startswith'
    id: string
}

export interface CompareFilter {
    compare?: boolean
    compare_to?: string
}

export const INITIAL_DATE_FROM = '-7d'
export const INITIAL_DATE_TO = null
export const INITIAL_INTERVAL = 'day'

interface PageReportsLogicProps {
    id?: string
}

// Helper function to convert WebStatsBreakdown to property filter
export const webStatsBreakdownToPropertyName = (
    breakdownBy: WebStatsBreakdown
):
    | { key: string; type: PropertyFilterType.Person | PropertyFilterType.Event | PropertyFilterType.Session }
    | undefined => {
    switch (breakdownBy) {
        case WebStatsBreakdown.Page:
            return { key: '$pathname', type: PropertyFilterType.Event }
        case WebStatsBreakdown.InitialPage:
            return { key: '$entry_pathname', type: PropertyFilterType.Session }
        case WebStatsBreakdown.ExitPage:
            return { key: '$end_pathname', type: PropertyFilterType.Session }
        case WebStatsBreakdown.ExitClick:
            return { key: '$last_external_click_url', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialChannelType:
            return { key: '$channel_type', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialReferringDomain:
            return { key: '$entry_referring_domain', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMSource:
            return { key: '$entry_utm_source', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMCampaign:
            return { key: '$entry_utm_campaign', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMMedium:
            return { key: '$entry_utm_medium', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMContent:
            return { key: '$entry_utm_content', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMTerm:
            return { key: '$entry_utm_term', type: PropertyFilterType.Session }
        case WebStatsBreakdown.Browser:
            return { key: '$browser', type: PropertyFilterType.Event }
        case WebStatsBreakdown.OS:
            return { key: '$os', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Viewport:
            return { key: '$viewport', type: PropertyFilterType.Event }
        case WebStatsBreakdown.DeviceType:
            return { key: '$device_type', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Country:
            return { key: '$geoip_country_code', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Region:
            return { key: '$geoip_subdivision_1_code', type: PropertyFilterType.Event }
        case WebStatsBreakdown.City:
            return { key: '$geoip_city_name', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Timezone:
            return { key: '$timezone', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Language:
            return { key: '$geoip_language', type: PropertyFilterType.Event }
        default:
            return undefined
    }
}

// Helper function to create breakdown filter
export const getWebAnalyticsBreakdownFilter = (breakdown: WebStatsBreakdown): BreakdownFilter | undefined => {
    const property = webStatsBreakdownToPropertyName(breakdown)

    if (!property) {
        return undefined
    }

    return {
        breakdown_type: property.type,
        breakdown: property.key,
    }
}

export const pageReportsLogic = kea<any>([
    path(['scenes', 'web-analytics', 'pageReportsLogic']),
    props({} as PageReportsLogicProps),
    key(({ id }) => id || 'new'),
    actions({
        addPage: (page) => ({ page }),
        setEdit: (edit) => ({ edit }),
        toggleStripQueryParams: () => ({}),
        setPageUrl: (page) => ({ page }),
        addPageFromUrl: (url) => ({ url }),
        setSearchTerm: (search) => ({ search }),
        setDateFilter: (dateFrom, dateTo) => ({ dateFrom, dateTo }),
        setInterval: (interval) => ({ interval }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts) => ({ shouldFilterTestAccounts }),
        setCompareFilter: (compareFilter) => ({ compareFilter }),
    }),
    loaders(({ values }) => ({
        pages: {
            __default: [] as PageURL[],
            loadPages: async () => {
                try {
                    // Simple query using the same pattern as heatmapsLogic
                    const searchQuery = values.searchTerm
                        ? values.stripQueryParams
                            ? // Use startsWith when query params are stripped
                              hogql`AND properties.$current_url LIKE concat(${hogql.identifier(
                                  values.searchTerm
                              )}, '%')`
                            : // Use contains when we need to match query params
                              hogql`AND properties.$current_url like '%${hogql.identifier(values.searchTerm)}%'`
                        : ''

                    const response = (await performQuery({
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT DISTINCT properties.$current_url as url, count() as count
                            FROM events
                            WHERE event = '$pageview' ${searchQuery}
                            GROUP BY url
                            ORDER BY count DESC
                            LIMIT 100
                        `,
                    })) as { results: [string, number][] }

                    return (response.results || []).map((result: [string, number]) => ({
                        url: result[0],
                        url_matching: values.stripQueryParams ? 'startswith' : 'exact',
                        id: result[0],
                    }))
                } catch (error: any) {
                    lemonToast.error(`Error loading pages: ${error.message}`)
                    return []
                }
            },
        },
    })),
    reducers(() => ({
        edit: [
            false,
            {
                setEdit: (_, { edit }) => edit,
            },
        ],
        stripQueryParams: [
            true,
            {
                toggleStripQueryParams: (state) => !state,
            },
        ],
        pageUrl: [
            null as PageURL | null,
            {
                setPageUrl: (_, { page }) => page,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { search }) => search || '',
            },
        ],
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
                interval: INITIAL_INTERVAL,
            },
            {
                persistenceKey: 'pageReports-dateFilter',
            },
            {
                setDateFilter: (state, { dateFrom, dateTo }) => ({
                    ...state,
                    dateFrom,
                    dateTo,
                    interval: getDefaultInterval(dateFrom, dateTo),
                }),
                setInterval: (state, { interval }) => {
                    const { dateFrom, dateTo } = updateDatesWithInterval(interval, state.dateFrom, state.dateTo)
                    return {
                        dateFrom,
                        dateTo,
                        interval,
                    }
                },
            },
        ],
        shouldFilterTestAccounts: [
            false,
            {
                persistenceKey: 'pageReports-shouldFilterTestAccounts',
            },
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
            },
        ],
        compareFilter: [
            null as CompareFilter | null,
            {
                persistenceKey: 'pageReports-compareFilter',
            },
            {
                setCompareFilter: (_, { compareFilter }) => compareFilter,
            },
        ],
    })),
    selectors({
        hasPageSelected: [(s) => [s.pageUrl], (pageUrl: PageURL | null) => pageUrl !== null],
        trendSeries: [
            (s) => [s.pageUrl, s.stripQueryParams],
            (pageUrl: PageURL | null, stripQueryParams: boolean): string => {
                if (!pageUrl) {
                    return ''
                }
                return `${pageUrl.url} - ${stripQueryParams ? 'No query params' : 'With query params'}`
            },
        ],
        pageSearchResults: [
            (s) => [s.pages, s.searchTerm],
            (pages: PageURL[], searchTerm: string) => {
                if (!searchTerm) {
                    return pages
                }
                return pages.filter((page) => page.url.toLowerCase().includes(searchTerm.toLowerCase()))
            },
        ],
        getNewInsightUrl: [
            (s) => [s.pageUrl, s.stripQueryParams],
            (pageUrl: PageURL | null, stripQueryParams: boolean): string | null => {
                if (!pageUrl?.url) {
                    return null
                }

                return `/insights/new?insight=TRENDS&interval=day&display=ActionsLineGraph&events=[{"id":"$pageview","name":"$pageview","type":"events","order":0,"custom_name":"Views of ${encodeURIComponent(
                    pageUrl.url
                )}","math":"dau","properties":[{"key":"${
                    stripQueryParams ? 'normalized_url' : 'url'
                }","value":"${encodeURIComponent(pageUrl.url)}","operator":"exact","type":"event"}]}]`
            },
        ],
        // Create property filter for the current page URL
        pageUrlPropertyFilter: [
            (s) => [s.pageUrl, s.stripQueryParams],
            (pageUrl: PageURL | null, stripQueryParams: boolean) => {
                if (!pageUrl?.url) {
                    return []
                }

                return [
                    {
                        key: '$current_url',
                        type: PropertyFilterType.Event,
                        value: pageUrl.url,
                        operator: stripQueryParams ? PropertyOperator.IContains : PropertyOperator.Exact,
                    },
                ]
            },
        ],
        // Combined metrics query for the main chart
        combinedMetricsQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ): InsightVizNode => {
                return {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        interval: dateFilter.interval,
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                event: '$pageview',
                                name: 'Unique Users',
                                custom_name: 'Unique Users',
                                math: 'dau' as any,
                                properties: pageUrlPropertyFilter,
                            },
                            {
                                kind: NodeKind.EventsNode,
                                event: '$pageview',
                                name: 'Total Page Views',
                                custom_name: 'Total Page Views',
                                math: 'total' as any,
                                properties: pageUrlPropertyFilter,
                            },
                            {
                                kind: NodeKind.EventsNode,
                                event: '$pageview',
                                name: 'Sessions',
                                custom_name: 'Sessions',
                                math: 'unique_session' as any,
                                properties: pageUrlPropertyFilter,
                            },
                        ],
                        trendsFilter: {
                            display: ChartDisplayType.ActionsLineGraph,
                        },
                        filterTestAccounts: shouldFilterTestAccounts,
                        compareFilter: compareFilter ?? undefined,
                    },
                }
            },
        ],
        // Entry paths query
        entryPathsQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.InitialPage,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Exit paths query
        exitPathsQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.ExitPage,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Outbound clicks query
        outboundClicksQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.ExitClick,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Channels query
        channelsQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.InitialChannelType,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Referrers query
        referrersQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.InitialReferringDomain,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Device type query
        deviceTypeQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.DeviceType,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Browser query
        browserQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.Browser,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // OS query
        osQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.OS,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Countries query
        countriesQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.Country,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Regions query
        regionsQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.Region,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Cities query
        citiesQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.City,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Timezones query
        timezonesQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.Timezone,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
        // Languages query
        languagesQuery: [
            (s) => [
                s.pageUrl,
                s.stripQueryParams,
                s.dateFilter,
                s.compareFilter,
                s.shouldFilterTestAccounts,
                s.pageUrlPropertyFilter,
            ],
            (
                pageUrl: PageURL | null,
                stripQueryParams: boolean,
                dateFilter: any,
                compareFilter: CompareFilter | null,
                shouldFilterTestAccounts: boolean,
                pageUrlPropertyFilter: any
            ) => {
                if (!pageUrl?.url) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebStatsTableQuery,
                        properties: pageUrlPropertyFilter,
                        breakdownBy: WebStatsBreakdown.Language,
                        dateRange: {
                            date_from: dateFilter.dateFrom || '-7d',
                            date_to: dateFilter.dateTo,
                        },
                        compareFilter: compareFilter ?? undefined,
                        limit: 10,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    full: true,
                    embedded: false,
                    showActions: true,
                    columns: ['breakdown_value', 'visitors', 'views'],
                }
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        addPageFromUrl: ({ url }) => {
            if (!url) {
                return
            }
            const page = {
                url,
                url_matching: values.stripQueryParams ? 'startswith' : 'exact',
                id: url,
            }
            actions.setPageUrl(page)
        },
        toggleStripQueryParams: () => {
            // When toggling strip query params, reload pages
            actions.loadPages()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPages()
    }),
])
