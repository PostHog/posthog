import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'
import { NodeKind, QuerySchema, WebAnalyticsPropertyFilters, WebStatsBreakdown } from '~/queries/schema'
import {
    BaseMathType,
    ChartDisplayType,
    EventPropertyFilter,
    HogQLPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'
import { isNotNil } from 'lib/utils'

export interface WebTileLayout {
    colSpan?: number
    rowSpan?: number
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

export const initialWebAnalyticsFilter = [] as WebAnalyticsPropertyFilters

const setOncePropertyNames = ['$initial_pathname', '$initial_referrer', '$initial_utm_source', '$initial_utm_campaign']
const hogqlForSetOnceProperty = (key: string, value: string): string => `properties.$set_once.${key} = '${value}'`
const isHogqlForSetOnceProperty = (key: string, p: HogQLPropertyFilter): boolean =>
    setOncePropertyNames.includes(key) && p.key.startsWith(`properties.$set_once.${key} = `)

export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect({}),
    actions({
        setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsPropertyFilters) => ({ webAnalyticsFilters }),
        togglePropertyFilter: (key: string, value: string) => ({ key, value }),
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
                togglePropertyFilter: (oldPropertyFilters, { key, value }) => {
                    if (
                        oldPropertyFilters.some(
                            (f) =>
                                (f.type === PropertyFilterType.Event &&
                                    f.key === key &&
                                    f.operator === PropertyOperator.Exact) ||
                                (f.type === PropertyFilterType.HogQL && isHogqlForSetOnceProperty(key, f))
                        )
                    ) {
                        return oldPropertyFilters
                            .map((f) => {
                                if (setOncePropertyNames.includes(key)) {
                                    if (f.type !== PropertyFilterType.HogQL) {
                                        return f
                                    }
                                    if (!isHogqlForSetOnceProperty(key, f)) {
                                        return f
                                    }
                                    // With the hogql properties, we don't even attempt to handle arrays, to avoiding
                                    // needing a parser on the front end. Instead the logic is much simpler
                                    const hogql = hogqlForSetOnceProperty(key, value)
                                    if (f.key === hogql) {
                                        return null
                                    } else {
                                        return {
                                            type: PropertyFilterType.HogQL,
                                            key,
                                            value: hogql,
                                        } as const
                                    }
                                } else {
                                    if (
                                        f.key !== key ||
                                        f.type !== PropertyFilterType.Event ||
                                        f.operator !== PropertyOperator.Exact
                                    ) {
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
                                }
                            })
                            .filter(isNotNil)
                    } else {
                        let newFilter: EventPropertyFilter | HogQLPropertyFilter
                        if (setOncePropertyNames.includes(key)) {
                            newFilter = {
                                type: PropertyFilterType.HogQL,
                                key: hogqlForSetOnceProperty(key, value),
                            }
                        } else {
                            newFilter = {
                                type: PropertyFilterType.Event,
                                key,
                                value,
                                operator: PropertyOperator.Exact,
                            }
                        }

                        return [...oldPropertyFilters, newFilter]
                    }
                },
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
            GeographyTab.COUNTRIES as string,
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
            '-0d' as string | null,
            {
                setDates: (_, { dateTo }) => dateTo,
            },
        ],
    }),
    selectors(({ actions }) => ({
        tiles: [
            (s) => [s.webAnalyticsFilters, s.pathTab, s.deviceTab, s.sourceTab, s.geographyTab, s.dateFrom, s.dateTo],
            (
                webAnalyticsFilters,
                pathTab,
                deviceTab,
                sourceTab,
                geographyTab,
                dateFrom,
                dateTo
            ): WebDashboardTile[] => {
                const dateRange = {
                    date_from: dateFrom,
                    date_to: dateTo,
                }
                return [
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
                        activeTabId: pathTab,
                        setTabId: actions.setPathTab,
                        tabs: [
                            {
                                id: PathTab.PATH,
                                title: 'Top Paths',
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
                                title: 'Top Entry Paths',
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
                                title: 'Top Referrers',
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
                                title: 'Top Sources',
                                linkText: 'UTM Source',
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
                                title: 'Top Campaigns',
                                linkText: 'UTM Campaign',
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
                                title: 'Top Browsers',
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
                                title: 'Top Device Types',
                                linkText: 'Device Type',
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
                    // {
                    //     title: 'Unique visitors',
                    //     layout: {
                    //         colSpan: 6,
                    //     },
                    //     query: {
                    //         kind: NodeKind.InsightVizNode,
                    //         source: {
                    //             kind: NodeKind.TrendsQuery,
                    //             dateRange,
                    //             interval: 'day',
                    //             series: [
                    //                 {
                    //                     event: '$pageview',
                    //                     kind: NodeKind.EventsNode,
                    //                     math: BaseMathType.UniqueUsers,
                    //                     name: '$pageview',
                    //                 },
                    //             ],
                    //             trendsFilter: {
                    //                 compare: true,
                    //                 display: ChartDisplayType.ActionsLineGraph,
                    //             },
                    //             filterTestAccounts: true,
                    //             properties: webAnalyticsFilters,
                    //         },
                    //     },
                    // },
                    {
                        layout: {
                            colSpan: 6,
                        },
                        activeTabId: geographyTab,
                        setTabId: actions.setGeographyTab,
                        tabs: [
                            {
                                id: GeographyTab.MAP,
                                title: 'World Map',
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
                                },
                            },
                            {
                                id: GeographyTab.COUNTRIES,
                                title: 'Top Countries',
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
                                title: 'Top Regions',
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
                                title: 'Top Cities',
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
                    },
                ]
            },
        ],
    })),
    sharedListeners(() => ({})),
    listeners(() => ({})),
])
