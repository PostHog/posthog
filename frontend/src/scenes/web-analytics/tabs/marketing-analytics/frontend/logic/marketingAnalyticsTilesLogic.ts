import { connect, kea, path, selectors } from 'kea'

import {
    ConversionGoalFilter,
    NodeKind,
    DataTableNode,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsHelperForColumnNames,
    CompareFilter,
} from '~/queries/schema/schema-general'
import { BaseMathType, InsightLogicProps, IntervalType } from '~/types'

import { isDraftConversionGoalColumn, getSortedColumnsByArray, orderArrayByPreference, getOrderBy } from './utils'
import { isNotNil } from 'lib/utils'
import { marketingAnalyticsLogic } from './marketingAnalyticsLogic'
import type { marketingAnalyticsTilesLogicType } from './marketingAnalyticsTilesLogicType'
import { marketingAnalyticsTableLogic } from './marketingAnalyticsTableLogic'
import { getDashboardItemId } from 'scenes/web-analytics/insightsUtils'
import { loadPriorityMap, MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS, TileId } from 'scenes/web-analytics/common'

export const MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID = 'marketing-analytics'

export const marketingAnalyticsTilesLogic = kea<marketingAnalyticsTilesLogicType>([
    path(['scenes', 'webAnalytics', 'marketingAnalyticsTilesLogic']),
    connect(() => ({
        values: [
            marketingAnalyticsLogic,
            [
                'compareFilter',
                'dateFilter',
                'createMarketingDataWarehouseNodes',
                'loading',
                'draftConversionGoal',
                'chartDisplayType',
            ],
            marketingAnalyticsTableLogic,
            ['query', 'defaultColumns'],
        ],
    })),
    selectors({
        tiles: [
            (s) => [
                s.compareFilter,
                s.dateFilter,
                s.createMarketingDataWarehouseNodes,
                s.campaignCostsBreakdown,
                s.chartDisplayType,
            ],
            (
                compareFilter,
                dateFilter,
                createMarketingDataWarehouseNodes,
                campaignCostsBreakdown,
                chartDisplayType
            ) => {
                const createInsightProps = (tile: TileId, tab?: string): InsightLogicProps => {
                    return {
                        dashboardItemId: getDashboardItemId(tile, tab, false),
                        loadPriority: loadPriorityMap[tile],
                        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
                    }
                }

                return [
                    {
                        kind: 'query',
                        tileId: TileId.MARKETING,
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                            orderWhenLargeClassName: 'xxl:order-1',
                        },
                        title: 'Marketing costs',
                        query: {
                            kind: NodeKind.InsightVizNode,
                            embedded: true,
                            hidePersonsModal: true,
                            hideTooltipOnScroll: true,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                compareFilter: compareFilter,
                                series:
                                    createMarketingDataWarehouseNodes.length > 0
                                        ? createMarketingDataWarehouseNodes
                                        : [
                                              // Fallback when no sources are configured
                                              {
                                                  kind: NodeKind.EventsNode,
                                                  event: 'no_sources_configured',
                                                  custom_name: 'No marketing sources configured',
                                                  math: BaseMathType.TotalCount,
                                              },
                                          ],
                                interval: dateFilter.interval,
                                dateRange: {
                                    date_from: dateFilter.dateFrom,
                                    date_to: dateFilter.dateTo,
                                },
                                trendsFilter: {
                                    display: chartDisplayType,
                                    aggregationAxisFormat: 'numeric',
                                    aggregationAxisPrefix: '$',
                                },
                            },
                        },
                        showIntervalSelect: true,
                        insightProps: createInsightProps(TileId.MARKETING, `${chartDisplayType}`),
                        canOpenInsight: true,
                        canOpenModal: false,
                        docs: {
                            title: 'Marketing costs',
                            description:
                                createMarketingDataWarehouseNodes.length > 0
                                    ? 'Track costs from your configured marketing data sources.'
                                    : 'Configure marketing data sources in the settings to track costs from your ad platforms.',
                        },
                    },
                    campaignCostsBreakdown
                        ? {
                              kind: 'query',
                              tileId: TileId.MARKETING_CAMPAIGN_BREAKDOWN,
                              layout: {
                                  colSpanClassName: 'md:col-span-2',
                                  orderWhenLargeClassName: 'xxl:order-2',
                              },
                              title: 'Campaign costs breakdown',
                              query: campaignCostsBreakdown,
                              insightProps: createInsightProps(TileId.MARKETING_CAMPAIGN_BREAKDOWN),
                              canOpenModal: true,
                              canOpenInsight: false,
                              docs: {
                                  title: 'Campaign costs breakdown',
                                  description:
                                      'Breakdown of marketing costs by individual campaign names across all ad platforms.',
                              },
                          }
                        : null,
                ].filter(isNotNil)
            },
        ],
        campaignCostsBreakdown: [
            (s) => [s.loading, s.query, s.dateFilter, s.draftConversionGoal, s.defaultColumns, s.compareFilter],
            (
                loading: boolean,
                query: DataTableNode,
                dateFilter: { dateFrom: string; dateTo: string; interval: IntervalType },
                draftConversionGoal: ConversionGoalFilter | null,
                defaultColumns: string[],
                compareFilter: CompareFilter
            ): DataTableNode | null => {
                if (loading) {
                    return null
                }

                const marketingQuery = query?.source as MarketingAnalyticsTableQuery | undefined
                const columnsWithDraftConversionGoal = [
                    ...(marketingQuery?.select?.length ? marketingQuery.select : defaultColumns).filter(
                        (column) => !isDraftConversionGoalColumn(column, draftConversionGoal)
                    ),
                    ...(draftConversionGoal
                        ? [
                              draftConversionGoal.conversion_goal_name,
                              `${MarketingAnalyticsHelperForColumnNames.CostPer} ${draftConversionGoal.conversion_goal_name}`,
                          ]
                        : []),
                ]
                const sortedColumns = getSortedColumnsByArray(columnsWithDraftConversionGoal, defaultColumns)
                const orderedColumns = orderArrayByPreference(sortedColumns, query?.pinnedColumns || [])
                const orderBy = getOrderBy(marketingQuery, sortedColumns)
                return {
                    ...query,
                    kind: NodeKind.DataTableNode,
                    source: {
                        ...marketingQuery,
                        kind: NodeKind.MarketingAnalyticsTableQuery,
                        dateRange: {
                            date_from: dateFilter.dateFrom,
                            date_to: dateFilter.dateTo,
                        },
                        properties: [],
                        draftConversionGoal: draftConversionGoal,
                        limit: 200,
                        orderBy,
                        tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
                        select: orderedColumns,
                        compareFilter: compareFilter,
                    },
                    full: true,
                    embedded: false,
                    showOpenEditorButton: false,
                }
            },
        ],
    }),
])
