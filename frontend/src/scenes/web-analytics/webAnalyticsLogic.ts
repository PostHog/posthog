import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'
import { NodeKind, QuerySchema, WebAnalyticsPropertyFilters, WebStatsBreakdown } from '~/queries/schema'
import { BaseMathType, ChartDisplayType, EventPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'
import { isNotNil } from 'lib/utils'

interface Layout {
    colSpan?: number
    rowSpan?: number
}

interface BaseTile {
    layout: Layout
}

interface QueryTile extends BaseTile {
    title?: string
    query: QuerySchema
}

interface TabsTile extends BaseTile {
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

export const initialWebAnalyticsFilter = [] as WebAnalyticsPropertyFilters

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
    }),
    reducers({
        webAnalyticsFilters: [
            initialWebAnalyticsFilter,
            {
                setWebAnalyticsFilters: (_, { webAnalyticsFilters }) => webAnalyticsFilters,
                togglePropertyFilter: (oldPropertyFilters, { key, value }) => {
                    if (oldPropertyFilters.some((f) => f.key === key && f.operator === PropertyOperator.Exact)) {
                        return oldPropertyFilters
                            .map((f) => {
                                if (
                                    f.type !== PropertyFilterType.Event ||
                                    f.key !== key ||
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
                            })
                            .filter(isNotNil)
                    } else {
                        const newFilter: EventPropertyFilter = {
                            type: PropertyFilterType.Event,
                            key,
                            value,
                            operator: PropertyOperator.Exact,
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
    }),
    selectors(({ actions }) => ({
        tiles: [
            (s) => [s.webAnalyticsFilters, s.pathTab, s.deviceTab, s.sourceTab],
            (webAnalyticsFilters, pathTab, deviceTab, sourceTab): WebDashboardTile[] => [
                {
                    layout: {
                        colSpan: 12,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebOverviewStatsQuery,
                            properties: webAnalyticsFilters,
                        },
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
                                    kind: NodeKind.WebTopSourcesQuery, // TODO
                                    properties: webAnalyticsFilters,
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
                                    kind: NodeKind.WebTopSourcesQuery,
                                    properties: webAnalyticsFilters,
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
                                    kind: NodeKind.WebTopSourcesQuery, // TODO
                                    properties: webAnalyticsFilters,
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
                                    kind: NodeKind.WebTopSourcesQuery, // TODO
                                    properties: webAnalyticsFilters,
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
                                    kind: NodeKind.WebTopSourcesQuery, // TODO
                                    properties: webAnalyticsFilters,
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
                                    kind: NodeKind.WebTopSourcesQuery, // TODO
                                    properties: webAnalyticsFilters,
                                },
                            },
                        },
                    ],
                },
                {
                    title: 'Unique users',
                    layout: {
                        colSpan: 6,
                    },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            dateRange: {
                                date_from: '-7d',
                                date_to: '-1d',
                            },
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
                    },
                },
                {
                    title: 'World Map (Unique Users)',
                    layout: {
                        colSpan: 6,
                    },
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            breakdown: {
                                breakdown: '$geoip_country_code',
                                breakdown_type: 'person',
                            },
                            dateRange: {
                                date_from: '-7d',
                            },
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
            ],
        ],
    })),
    sharedListeners(() => ({})),
    listeners(() => ({})),
])
