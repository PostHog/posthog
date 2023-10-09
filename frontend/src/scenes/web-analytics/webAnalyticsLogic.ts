import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'
import { NodeKind, QuerySchema, WebAnalyticsFilters } from '~/queries/schema'
import { BaseMathType, ChartDisplayType } from '~/types'

interface Layout {
    colSpan?: number
    rowSpan?: number
}
export interface WebDashboardTile {
    query: QuerySchema
    layout: Layout
}

export const initialWebAnalyticsFilter = [] as WebAnalyticsFilters

export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect({}),
    actions({
        setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsFilters) => ({ webAnalyticsFilters }),
    }),
    reducers({
        webAnalyticsFilters: [
            initialWebAnalyticsFilter,
            {
                setWebAnalyticsFilters: (_, { webAnalyticsFilters }) => webAnalyticsFilters,
            },
        ],
    }),
    selectors({
        tiles: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters): WebDashboardTile[] => [
                {
                    layout: {
                        colSpan: 12,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebOverviewStatsQuery,
                            filters: webAnalyticsFilters,
                        },
                    },
                },
                {
                    layout: {
                        colSpan: 6,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebTopPagesQuery,
                            filters: webAnalyticsFilters,
                        },
                    },
                },
                {
                    layout: {
                        colSpan: 6,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebTopSourcesQuery,
                            filters: webAnalyticsFilters,
                        },
                    },
                },
                {
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
    }),
    sharedListeners(() => ({})),
    listeners(() => ({})),
])
