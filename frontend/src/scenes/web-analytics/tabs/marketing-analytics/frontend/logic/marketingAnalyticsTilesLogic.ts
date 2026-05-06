import { connect, kea, path, selectors } from 'kea'

import { isNotNil } from 'lib/utils'
import { getCurrencySymbol } from 'lib/utils/geography/currency'
import { MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS, QueryTile, TileId, loadPriorityMap } from 'scenes/web-analytics/common'
import { getDashboardItemId } from 'scenes/web-analytics/insightsUtils'

import {
    CompareFilter,
    ConversionGoalFilter,
    CurrencyCode,
    DataTableNode,
    DataWarehouseNode,
    IntegrationFilter,
    MARKETING_ANALYTICS_DRILL_DOWN_CONFIG,
    MARKETING_ANALYTICS_SCHEMA,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsConstants,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
    NodeKind,
    getEffectiveExcludedColumns,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightLogicProps, IntervalType } from '~/types'

import { marketingAnalyticsLogic } from './marketingAnalyticsLogic'
import { marketingAnalyticsTableLogic } from './marketingAnalyticsTableLogic'
import type { marketingAnalyticsTilesLogicType } from './marketingAnalyticsTilesLogicType'
import {
    getOrderBy,
    rawColumnsForTiles,
    getSortedColumnsByArray,
    isDraftConversionGoalColumn,
    orderArrayByPreference,
    validColumnsForTiles,
} from './utils'

export const MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID = 'marketing-analytics'

const isSchemaBackedMarketingColumn = (column: validColumnsForTiles): column is rawColumnsForTiles =>
    column !== 'roas' && column !== 'cost_per_reported_conversion'

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
                'tileColumnSelection',
                'integrationFilter',
                'drillDownLevel',
                'baseCurrency',
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
                s.tileColumnSelection,
                s.draftConversionGoal,
                s.integrationFilter,
                s.drillDownLevel,
                s.baseCurrency,
            ],
            (
                compareFilter: CompareFilter | null,
                dateFilter: {
                    dateFrom: string | null
                    dateTo: string | null
                    interval: IntervalType
                },
                createMarketingDataWarehouseNodes: DataWarehouseNode[],
                campaignCostsBreakdown: DataTableNode,
                chartDisplayType: ChartDisplayType,
                tileColumnSelection: validColumnsForTiles,
                draftConversionGoal: ConversionGoalFilter | null,
                integrationFilter: IntegrationFilter,
                drillDownLevel: MarketingAnalyticsDrillDownLevel,
                baseCurrency: CurrencyCode
            ) => {
                const createInsightProps = (tile: TileId, tab?: string): InsightLogicProps => {
                    return {
                        dashboardItemId: getDashboardItemId(tile, tab, false),
                        loadPriority: loadPriorityMap[tile],
                        dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
                    }
                }

                const isCurrency =
                    tileColumnSelection && isSchemaBackedMarketingColumn(tileColumnSelection)
                        ? MARKETING_ANALYTICS_SCHEMA[tileColumnSelection].isCurrency
                        : false

                const { symbol: currencySymbol, isPrefix: currencyIsPrefix } = getCurrencySymbol(baseCurrency)

                const tileColumnSelectionName = tileColumnSelection?.split('_').join(' ')

                const tiles: QueryTile[] = [
                    {
                        kind: 'query',
                        tileId: TileId.MARKETING_OVERVIEW,
                        layout: {
                            colSpanClassName: 'md:col-span-2 xxl:col-span-3' as `md:col-span-${number}`,
                            orderWhenLargeClassName: 'xxl:order-0',
                        },
                        query: {
                            kind: NodeKind.MarketingAnalyticsAggregatedQuery,
                            dateRange: {
                                date_from: dateFilter.dateFrom,
                                date_to: dateFilter.dateTo,
                            },
                            compareFilter: compareFilter || undefined,
                            properties: [],
                            draftConversionGoal: draftConversionGoal || undefined,
                            integrationFilter: integrationFilter,
                        },
                        insightProps: createInsightProps(TileId.MARKETING_OVERVIEW),
                        canOpenInsight: false,
                    },
                    {
                        kind: 'query',
                        tileId: TileId.MARKETING,
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                            orderWhenLargeClassName: 'xxl:order-1',
                        },
                        title: `Marketing ${tileColumnSelectionName}`,
                        query: {
                            kind: NodeKind.InsightVizNode,
                            embedded: true,
                            hidePersonsModal: true,
                            hideTooltipOnScroll: true,
                            source: {
                                kind: NodeKind.TrendsQuery,
                                compareFilter: compareFilter || undefined,
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
                                    aggregationAxisPrefix: isCurrency && currencyIsPrefix ? currencySymbol : undefined,
                                    aggregationAxisPostfix:
                                        isCurrency && !currencyIsPrefix ? ` ${currencySymbol}` : undefined,
                                },
                            },
                        },
                        showIntervalSelect: true,
                        insightProps: createInsightProps(
                            TileId.MARKETING,
                            `${chartDisplayType}-${tileColumnSelection}`
                        ),
                        canOpenInsight: true,
                        canOpenModal: false,
                        docs: {
                            title: `Marketing ${tileColumnSelectionName}`,
                            description:
                                createMarketingDataWarehouseNodes.length > 0
                                    ? `Track ${tileColumnSelectionName || 'costs'} from your configured marketing data sources.`
                                    : `Configure marketing data sources in the settings to track ${tileColumnSelectionName || 'costs'} from your ad platforms.`,
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
                              title: `${MARKETING_ANALYTICS_DRILL_DOWN_CONFIG[drillDownLevel].columnAlias} breakdown`,
                              query: campaignCostsBreakdown,
                              insightProps: createInsightProps(TileId.MARKETING_CAMPAIGN_BREAKDOWN),
                              canOpenModal: true,
                              canOpenInsight: false,
                              docs: {
                                  title: `${MARKETING_ANALYTICS_DRILL_DOWN_CONFIG[drillDownLevel].columnAlias} breakdown`,
                                  description:
                                      drillDownLevel === MarketingAnalyticsDrillDownLevel.Campaign
                                          ? 'Breakdown of marketing costs by individual campaign names across all ad platforms.'
                                          : `Breakdown of marketing data by ${MARKETING_ANALYTICS_DRILL_DOWN_CONFIG[drillDownLevel].columnAlias.toLowerCase()}.`,
                              },
                          }
                        : null,
                ].filter(isNotNil) as QueryTile[]

                return tiles
            },
        ],
        campaignCostsBreakdown: [
            (s) => [
                s.loading,
                s.query,
                s.dateFilter,
                s.draftConversionGoal,
                s.defaultColumns,
                s.compareFilter,
                s.integrationFilter,
                s.drillDownLevel,
            ],
            (
                loading: boolean,
                query: DataTableNode,
                dateFilter: { dateFrom: string; dateTo: string; interval: IntervalType },
                draftConversionGoal: ConversionGoalFilter | null,
                defaultColumns: string[],
                compareFilter: CompareFilter,
                integrationFilter: IntegrationFilter,
                drillDownLevel: MarketingAnalyticsDrillDownLevel
            ): DataTableNode | null => {
                if (loading) {
                    return null
                }
                const marketingQuery = query?.source as MarketingAnalyticsTableQuery | undefined

                // Determine the correct grouping column alias for the current drill-down level
                const drillDownConfig = MARKETING_ANALYTICS_DRILL_DOWN_CONFIG[drillDownLevel]
                const groupingAlias = drillDownConfig.columnAlias
                const allGroupingAliases = Object.values(MARKETING_ANALYTICS_DRILL_DOWN_CONFIG).map(
                    (c) => c.columnAlias
                )
                // Effective excluded set = user-config + auto-excluded hierarchy columns at
                // non-hierarchy levels. Without this filter, switching drill-down levels leaves
                // stale columns in the select, and the stale response data renders as raw JSON
                // (no matching context.columns render fn).
                const excludedColumns = new Set<string>(getEffectiveExcludedColumns(drillDownLevel))
                // A grouping alias is "stale" only when it isn't a valid base column at the new level.
                // At AD_GROUP / AD, Campaign and Source are valid context columns, not stale. Without
                // this guard, switching from Channel → Ad group would remap Campaign / Source onto
                // the new grouping column and erase them from the select. Same idea also covers
                // master's Source-vs-SOURCE collision case.
                const validBaseColumnsAtLevel = new Set<string>(
                    Object.values(MarketingAnalyticsBaseColumns).filter((c) => !excludedColumns.has(c))
                )
                const staleGroupingColumns = allGroupingAliases.filter(
                    (c) => c !== groupingAlias && !validBaseColumnsAtLevel.has(c)
                )

                // Same rule as marketingAnalyticsTableLogic: at UTM levels the Cost metric is excluded
                // so cost-per-conversion for the draft goal must be excluded too.
                const costAvailable = !excludedColumns.has(MarketingAnalyticsBaseColumns.Cost)

                // At levels where conversion goals are excluded (AD_GROUP / AD), the previous
                // select may carry conversion-goal column names from another level — those names
                // pass through the base-column filter (they aren't grouping aliases or base
                // columns, so the filter doesn't strip them). Force defaultColumns at those
                // levels so we don't request columns the backend won't produce — without this
                // the table flashes JSON cells while the new response is loading.
                const previousSelect = drillDownConfig.excludesConversionGoals
                    ? defaultColumns
                    : marketingQuery?.select?.length
                      ? marketingQuery.select
                      : defaultColumns

                const columnsWithDraftConversionGoal = [
                    ...previousSelect
                        .filter((column) => !isDraftConversionGoalColumn(column, draftConversionGoal))
                        .map((column) => (staleGroupingColumns.includes(column) ? groupingAlias : column))
                        .filter((column) => column === groupingAlias || !excludedColumns.has(column))
                        .filter((column, index, arr) => arr.indexOf(column) === index),
                    // Skip the draft goal entirely when the level can't attribute events
                    // to a specific row (ad-group / ad). This mirrors the same gate in
                    // marketingAnalyticsTableLogic.defaultColumns; without it the user
                    // sees a phantom column the backend won't produce.
                    ...(draftConversionGoal && !drillDownConfig.excludesConversionGoals
                        ? costAvailable
                            ? [
                                  draftConversionGoal.conversion_goal_name,
                                  `${MarketingAnalyticsConstants.CostPer} ${draftConversionGoal.conversion_goal_name}`,
                              ]
                            : [draftConversionGoal.conversion_goal_name]
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
                        compareFilter: compareFilter || undefined,
                        integrationFilter: integrationFilter,
                        drillDownLevel: drillDownLevel,
                    },
                    full: true,
                    embedded: false,
                    showOpenEditorButton: false,
                }
            },
        ],
    }),
])
