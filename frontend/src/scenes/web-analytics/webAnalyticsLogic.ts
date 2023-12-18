import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import { windowValues } from 'kea-window-values'
import api from 'lib/api'
import { RETENTION_FIRST_TIME, STALE_EVENT_SECONDS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { getDefaultInterval, isNotNil, updateDatesWithInterval } from 'lib/utils'

import {
    NodeKind,
    QuerySchema,
    WebAnalyticsPropertyFilter,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
} from '~/queries/schema'
import {
    BaseMathType,
    ChartDisplayType,
    EventDefinition,
    EventDefinitionType,
    InsightType,
    IntervalType,
    PropertyDefinition,
    PropertyFilterType,
    PropertyOperator,
    RetentionPeriod,
} from '~/types'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'

export interface WebTileLayout {
    colSpan?: number
    rowSpan?: number
    className?: string
}

interface BaseTile {
    layout: WebTileLayout
}

interface QueryTile extends BaseTile {
    title?: string
    query: QuerySchema
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
    }[]
}

export type WebDashboardTile = QueryTile | TabsTile

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
    shouldWarnAboutNoPageviews: boolean
    shouldWarnAboutNoPageleaves: boolean
}

export const GEOIP_PLUGIN_URLS = [
    'https://github.com/PostHog/posthog-plugin-geoip',
    'https://www.npmjs.com/package/@posthog/geoip-plugin',
]

export const initialWebAnalyticsFilter = [] as WebAnalyticsPropertyFilters
const initialDateFrom = '-7d' as string | null
const initialDateTo = null as string | null
const initialInterval = getDefaultInterval(initialDateFrom, initialDateTo)

export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect({}),
    actions({
        setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsPropertyFilters) => ({ webAnalyticsFilters }),
        togglePropertyFilter: (
            type: PropertyFilterType.Event | PropertyFilterType.Person,
            key: string,
            value: string | number
        ) => ({
            type,
            key,
            value,
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
        setDateFilter: (dateFrom: string | null, dateTo: string | null, interval: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
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
            },
        ],
        graphsTab: [
            undefined as string | undefined,
            {
                setGraphsTab: (_, { tab }) => tab,
            },
        ],
        sourceTab: [
            undefined as string | undefined,
            {
                setSourceTab: (_, { tab }) => tab,
            },
        ],
        deviceTab: [
            undefined as string | undefined,
            {
                setDeviceTab: (_, { tab }) => tab,
            },
        ],
        pathTab: [
            undefined as string | undefined,
            {
                setPathTab: (_, { tab }) => tab,
            },
        ],
        geographyTab: [
            undefined as string | undefined,
            {
                setGeographyTab: (_, { tab }) => tab,
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
                setDateFilter: (_, { dateFrom, dateTo, interval }) => ({
                    dateTo,
                    dateFrom,
                    interval,
                }),
            },
        ],
    }),
    selectors(({ actions, values }) => ({
        tiles: [
            (s) => [
                s.webAnalyticsFilters,
                s.graphsTab,
                s.pathTab,
                s.deviceTab,
                s.sourceTab,
                s.geographyTab,
                s.dateFilter,
                () => values.isGreaterThanMd,
                () => values.shouldShowGeographyTile,
            ],
            (
                webAnalyticsFilters,
                graphsTab,
                pathTab,
                deviceTab,
                sourceTab,
                geographyTab,
                { dateFrom, dateTo, interval },
                isGreaterThanMd: boolean,
                shouldShowGeographyTile
            ): WebDashboardTile[] => {
                const dateRange = {
                    date_from: dateFrom,
                    date_to: dateTo,
                }
                const compare = !!dateRange.date_from

                const tiles: (WebDashboardTile | null)[] = [
                    {
                        layout: {
                            colSpan: 12,
                        },
                        query: {
                            kind: NodeKind.WebOverviewQuery,
                            properties: webAnalyticsFilters,
                            dateRange,
                        },
                    },
                    {
                        layout: {
                            colSpan: 6,
                        },
                        activeTabId: graphsTab || GraphsTab.UNIQUE_USERS,
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
                            },
                        ],
                    },
                    {
                        layout: {
                            colSpan: 6,
                        },
                        activeTabId: pathTab || PathTab.PATH,
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
                                    },
                                    embedded: false,
                                },
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
                                    },
                                    embedded: false,
                                },
                            },
                        ],
                    },
                    {
                        layout: {
                            colSpan: 6,
                        },
                        activeTabId: sourceTab || SourceTab.REFERRING_DOMAIN,
                        setTabId: actions.setSourceTab,
                        tabs: [
                            {
                                id: SourceTab.REFERRING_DOMAIN,
                                title: 'Top referrers',
                                linkText: 'Referrering domain',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.InitialReferringDomain,
                                        dateRange,
                                    },
                                },
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
                                    },
                                },
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
                                    },
                                },
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
                                    },
                                },
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
                                    },
                                },
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
                                    },
                                },
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
                                    },
                                },
                            },
                        ],
                    },
                    {
                        layout: {
                            colSpan: 6,
                        },
                        activeTabId: deviceTab || DeviceTab.DEVICE_TYPE,
                        setTabId: actions.setDeviceTab,
                        tabs: [
                            {
                                id: DeviceTab.DEVICE_TYPE,
                                title: 'Top Device Types',
                                linkText: 'Device Type',
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        breakdown: { breakdown: '$device_type', breakdown_type: 'event' },
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
                                            show_labels_on_series: true,
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
                                    },
                                    embedded: false,
                                },
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
                                    },
                                    embedded: false,
                                },
                            },
                        ],
                    },
                    {
                        title: 'Retention',
                        layout: {
                            colSpan: 12,
                        },
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.RetentionQuery,
                                properties: webAnalyticsFilters,
                                dateRange,
                                filterTestAccounts: true,
                                retentionFilter: {
                                    retention_type: RETENTION_FIRST_TIME,
                                    retention_reference: 'total',
                                    total_intervals: isGreaterThanMd ? 8 : 5,
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
                    },
                    shouldShowGeographyTile
                        ? {
                              layout: {
                                  colSpan: 12,
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
                                              breakdown: {
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
                                          },
                                      },
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
                                          },
                                      },
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
                                          },
                                      },
                                  },
                              ],
                          }
                        : null,
                ]
                return tiles.filter(isNotNil)
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
    })),
    loaders(() => ({
        // load the status check query here and pass the response into the component, so the response
        // is accessible in this logic
        statusCheck: {
            __default: null as WebAnalyticsStatusCheck | null,
            loadStatusCheck: async (): Promise<WebAnalyticsStatusCheck> => {
                const [pageviewResult, pageleaveResult] = await Promise.allSettled([
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$pageview',
                    }),
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$pageleave',
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

                const shouldWarnAboutNoPageviews = !pageviewEntry || isDefinitionStale(pageviewEntry)
                const shouldWarnAboutNoPageleaves = !pageleaveEntry || isDefinitionStale(pageleaveEntry)

                return {
                    shouldWarnAboutNoPageviews,
                    shouldWarnAboutNoPageleaves,
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

    actionToUrl(({ values }) => ({
        setWebAnalyticsFilters: () => stateToUrl(values),
        togglePropertyFilter: () => stateToUrl(values),
        setDates: () => stateToUrl(values),
        setInterval: () => stateToUrl(values),
        setDeviceTab: () => stateToUrl(values),
        setSourceTab: () => stateToUrl(values),
        setGraphsTab: () => stateToUrl(values),
        setPathTab: () => stateToUrl(values),
        setGeographyTab: () => stateToUrl(values),
    })),

    urlToAction(({ actions }) => ({
        '/web': (
            _,
            { filters, date_from, date_to, interval, device_tab, source_tab, graphs_tab, path_tab, geography_tab }
        ) => {
            if (filters) {
                actions.setWebAnalyticsFilters(filters)
            }
            if (date_from || date_to || interval) {
                actions.setDateFilter(date_from || null, date_to || null, interval || undefined)
            }
            if (device_tab) {
                actions.setDeviceTab(device_tab)
            }
            if (source_tab) {
                actions.setSourceTab(source_tab)
            }
            if (graphs_tab) {
                actions.setGraphsTab(graphs_tab)
            }
            if (path_tab) {
                actions.setPathTab(path_tab)
            }
            if (geography_tab) {
                actions.setGeographyTab(geography_tab)
            }
        },
    })),
])

const isDefinitionStale = (definition: EventDefinition | PropertyDefinition): boolean => {
    const parsedLastSeen = definition.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS
}

const stateToUrl = ({
    webAnalyticsFilters,
    dateFilter: { dateFrom, dateTo, interval },
    deviceTab,
    sourceTab,
    graphsTab,
    pathTab,
    geographyTab,
}: {
    webAnalyticsFilters: WebAnalyticsPropertyFilters
    dateFilter: {
        dateFrom: string | null
        dateTo: string | null
        interval: string | undefined
    }
    deviceTab: string | undefined
    sourceTab: string | undefined
    graphsTab: string | undefined
    pathTab: string | undefined
    geographyTab: string | undefined
}): string => {
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
    return `/web?${urlParams.toString()}`
}
