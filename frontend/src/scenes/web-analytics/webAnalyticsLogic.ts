import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { BaseMathType, ChartDisplayType } from '~/types'

interface Layout {
    colSpan?: number
    rowSpan?: number
}
export interface WebDashboardTile {
    query: QuerySchema
    layout: Layout
}
export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect({}),
    actions({}),
    reducers({}),
    selectors({
        tiles: [
            () => [],
            (): WebDashboardTile[] => [
                {
                    layout: {
                        colSpan: 12,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebOverviewStatsQuery,
                            filters: {},
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
                            filters: {},
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
                            filters: {},
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
                            filterTestAccounts: false,
                            interval: 'day',
                            kind: NodeKind.TrendsQuery,
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
                            breakdown: {
                                breakdown: '$geoip_country_code',
                                breakdown_type: 'person',
                            },
                            dateRange: {
                                date_from: '-7d',
                                date_to: null,
                            },
                            filterTestAccounts: true,
                            kind: NodeKind.TrendsQuery,
                            series: [
                                {
                                    event: '$pageview',
                                    kind: NodeKind.EventsNode,
                                    math: BaseMathType.UniqueUsers,
                                    name: '$pageview',
                                },
                            ],
                            trendsFilter: {
                                display: ChartDisplayType.WorldMap,
                            },
                        },
                    },
                },
            ],
        ],
    }),
    sharedListeners(() => ({})),
    listeners(() => ({})),
])
