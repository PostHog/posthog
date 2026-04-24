import { connect, kea, path, selectors } from 'kea'

import { NodeKind, WebAnalyticsPropertyFilters, WebStatsBreakdown } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightLogicProps, PropertyFilterType, PropertyOperator } from '~/types'

import type { botDetailLogicType } from './botDetailLogicType'
import { QueryTile, TileId, WEB_ANALYTICS_DEFAULT_QUERY_TAGS, WebAnalyticsTile, WebTileLayout } from './common'
import { webAnalyticsLogic } from './webAnalyticsLogic'

export const botDetailLogic = kea<botDetailLogicType>([
    path(['scenes', 'web-analytics', 'botDetailLogic']),

    connect({
        values: [
            webAnalyticsLogic,
            ['botDetailName', 'shouldFilterTestAccounts', 'dateFilter', 'isPathCleaningEnabled'],
        ],
    }),

    selectors({
        botFilters: [
            (s) => [s.botDetailName],
            (botDetailName): WebAnalyticsPropertyFilters => {
                if (!botDetailName) {
                    return []
                }
                return [
                    {
                        key: '$virt_is_bot',
                        value: ['true'],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                    {
                        key: '$virt_bot_name',
                        value: [botDetailName],
                        operator: PropertyOperator.Exact,
                        type: PropertyFilterType.Event,
                    },
                ]
            },
        ],

        tiles: [
            (s) => [s.botDetailName, s.botFilters, s.dateFilter, s.shouldFilterTestAccounts, s.isPathCleaningEnabled],
            (
                botDetailName,
                botFilters,
                { dateFrom, dateTo, interval },
                filterTestAccounts,
                isPathCleaningEnabled
            ): WebAnalyticsTile[] => {
                if (!botDetailName) {
                    return []
                }

                const dateRange = { date_from: dateFrom, date_to: dateTo }

                const createInsightProps = (tileId: TileId, tab?: string): InsightLogicProps => ({
                    dashboardItemId: `new-AdHoc.web-analytics.bot-detail.${tileId}${tab ? `.${tab}` : ''}`,
                    loadPriority: tab ? 1 : 0,
                })

                const tiles: WebAnalyticsTile[] = [
                    {
                        kind: 'query',
                        tileId: TileId.BOT_TRENDS,
                        title: 'Requests over time',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        } as WebTileLayout,
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                dateRange,
                                interval: interval ?? 'hour',
                                series: [
                                    {
                                        event: '$pageview',
                                        kind: NodeKind.EventsNode,
                                        math: BaseMathType.TotalCount,
                                        name: 'Pageview',
                                        custom_name: 'Requests',
                                    },
                                ],
                                trendsFilter: {
                                    display: ChartDisplayType.ActionsLineGraph,
                                },
                                properties: botFilters,
                                filterTestAccounts,
                                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                            },
                            hidePersonsModal: true,
                            embedded: true,
                        },
                        insightProps: createInsightProps(TileId.BOT_TRENDS),
                        canOpenInsight: true,
                    } as QueryTile,
                    {
                        kind: 'query',
                        tileId: TileId.BOT_PATHS,
                        title: 'Most crawled paths',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        } as WebTileLayout,
                        query: {
                            full: true,
                            kind: NodeKind.DataTableNode,
                            source: {
                                kind: NodeKind.WebStatsTableQuery,
                                breakdownBy: WebStatsBreakdown.Page,
                                properties: botFilters,
                                dateRange,
                                limit: 10,
                                filterTestAccounts,
                                doPathCleaning: isPathCleaningEnabled,
                                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                            },
                            columns: ['breakdown_value', 'visitors', 'views'],
                            embedded: true,
                            showActions: false,
                        },
                        insightProps: createInsightProps(TileId.BOT_PATHS, 'table'),
                        canOpenModal: true,
                        canOpenInsight: true,
                    } as QueryTile,
                ]

                return tiles
            },
        ],
    }),
])
