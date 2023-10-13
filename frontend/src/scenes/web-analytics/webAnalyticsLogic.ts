import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'
import { NodeKind, QuerySchema, WebAnalyticsPropertyFilters } from '~/queries/schema'
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
        togglePropertyFilter: (key: string, value: string) => ({ key, value }),
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
                    title: 'Pages',
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
                    title: 'Traffic Sources',
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
                    title: 'User locations',
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
