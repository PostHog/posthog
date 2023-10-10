import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'
import { NodeKind, QuerySchema, WebAnalyticsPropertyFilters } from '~/queries/schema'
import { BaseMathType, ChartDisplayType } from '~/types'

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
    tabs: {
        title: string
        linkText: string
        query: QuerySchema
    }
}

export type WebDashboardTile = QueryTile | TabsTile

export const initialWebAnalyticsFilter = [] as WebAnalyticsPropertyFilters

export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect({}),
    actions({
        setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsPropertyFilters) => ({ webAnalyticsFilters }),
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
                            properties: webAnalyticsFilters,
                        },
                    },
                },
                {
                    title: 'Which pages do your users visit most?',
                    layout: {
                        colSpan: 6,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebTopPagesQuery,
                            properties: webAnalyticsFilters,
                        },
                    },
                },
                {
                    title: 'Where do your users come from?',
                    layout: {
                        colSpan: 6,
                    },
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
                    title: 'Unique users over the last week',
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
                    title: 'Where are your users located?',
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
