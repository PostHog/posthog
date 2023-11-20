import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'

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
    PropertyDefinition,
    PropertyFilterType,
    PropertyOperator,
    RetentionPeriod,
} from '~/types'
import { isNotNil } from 'lib/utils'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { RETENTION_FIRST_TIME, STALE_EVENT_SECONDS } from 'lib/constants'
import { windowValues } from 'kea-window-values'

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
    UTM_SOURCE = 'UTM_SOURCE',
    UTM_CAMPAIGN = 'UTM_CAMPAIGN',
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

export const initialWebAnalyticsFilter = [] as WebAnalyticsPropertyFilters

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
            GraphsTab.UNIQUE_USERS as string,
            {
                setGraphsTab: (_, { tab }) => tab,
            },
        ],
        sourceTab: [
            SourceTab.REFERRING_DOMAIN as string,
            {
                setSourceTab: (_, { tab }) => tab,
            },
        ],
        deviceTab: [
            DeviceTab.BROWSER as string,
            {
                setDeviceTab: (_, { tab }) => tab,
            },
        ],
        pathTab: [
            PathTab.PATH as string,
            {
                setPathTab: (_, { tab }) => tab,
            },
        ],
        geographyTab: [
            GeographyTab.MAP as string,
            {
                setGeographyTab: (_, { tab }) => tab,
            },
        ],
        dateFrom: [
            '-7d' as string | null,
            {
                setDates: (_, { dateFrom }) => dateFrom,
            },
        ],
        dateTo: [
            null as string | null,
            {
                setDates: (_, { dateTo }) => dateTo,
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
                s.dateFrom,
                s.dateTo,
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
                dateFrom,
                dateTo,
                isGreaterThanMd: boolean,
                shouldShowGeographyTile
            ): WebDashboardTile[] => {
                const dateRange = {
                    date_from: dateFrom,
                    date_to: dateTo,
                }
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
                                        interval: 'day',
                                        series: [
                                            {
                                                event: '$pageview',
                                                kind: NodeKind.EventsNode,
                                                math: BaseMathType.UniqueUsers,
                                                name: '$pageview',
                                            },
                                        ],
                                        trendsFilter: {
                                            compare: true,
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        filterTestAccounts: true,
                                        properties: webAnalyticsFilters,
                                    },
                                    hidePersonsModal: true,
                                },
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
                                        interval: 'day',
                                        series: [
                                            {
                                                event: '$pageview',
                                                kind: NodeKind.EventsNode,
                                                math: BaseMathType.TotalCount,
                                                name: '$pageview',
                                            },
                                        ],
                                        trendsFilter: {
                                            compare: true,
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        filterTestAccounts: true,
                                        properties: webAnalyticsFilters,
                                    },
                                    hidePersonsModal: true,
                                },
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
                                        interval: 'day',
                                        series: [
                                            {
                                                event: '$pageview',
                                                kind: NodeKind.EventsNode,
                                                math: BaseMathType.UniqueSessions,
                                                name: '$pageview',
                                            },
                                        ],
                                        trendsFilter: {
                                            compare: true,
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        filterTestAccounts: true,
                                        properties: webAnalyticsFilters,
                                    },
                                    suppressSessionAnalysisWarning: true,
                                    hidePersonsModal: true,
                                },
                            },
                        ],
                    },
                    {
                        layout: {
                            colSpan: 6,
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
                                    },
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
                                },
                            },
                        ],
                    },
                    {
                        layout: {
                            colSpan: 6,
                        },
                        activeTabId: sourceTab,
                        setTabId: actions.setSourceTab,
                        tabs: [
                            {
                                id: SourceTab.REFERRING_DOMAIN,
                                title: 'Top referrers',
                                linkText: 'Referrer',
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
                                id: SourceTab.UTM_CAMPAIGN,
                                title: 'Top campaigns',
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
                        ],
                    },
                    {
                        layout: {
                            colSpan: 6,
                        },
                        activeTabId: deviceTab,
                        setTabId: actions.setDeviceTab,
                        tabs: [
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
                                },
                            },
                            {
                                id: DeviceTab.DEVICE_TYPE,
                                title: 'Top device types',
                                linkText: 'Device type',
                                query: {
                                    full: true,
                                    kind: NodeKind.DataTableNode,
                                    source: {
                                        kind: NodeKind.WebStatsTableQuery,
                                        properties: webAnalyticsFilters,
                                        breakdownBy: WebStatsBreakdown.DeviceType,
                                        dateRange,
                                    },
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
                        },
                    },
                    shouldShowGeographyTile
                        ? {
                              layout: {
                                  colSpan: 12,
                              },
                              activeTabId: geographyTab,
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
                const response = await api.propertyDefinitions.list({
                    event_names: ['$pageview'],
                    properties: ['$geoip_country_code'],
                })
                const countryCodeDefinition = response.results.find((r) => r.name === '$geoip_country_code')
                return !!countryCodeDefinition && !isDefinitionStale(countryCodeDefinition)
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
])

const isDefinitionStale = (definition: EventDefinition | PropertyDefinition): boolean => {
    const parsedLastSeen = definition.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS
}
