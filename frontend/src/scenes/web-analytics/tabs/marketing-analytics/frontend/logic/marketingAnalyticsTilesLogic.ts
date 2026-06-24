import { connect, kea, path, selectors } from 'kea'

import { getCurrencySymbol } from 'lib/utils/currency'
import { isNotNil } from 'lib/utils/guards'
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
import {
    BaseMathType,
    ChartDisplayType,
    HogQLMathType,
    InsightLogicProps,
    IntervalType,
    PropertyFilterType,
} from '~/types'

import { marketingAnalyticsLogic } from './marketingAnalyticsLogic'
import { marketingAnalyticsTableLogic } from './marketingAnalyticsTableLogic'
import type { marketingAnalyticsTilesLogicType } from './marketingAnalyticsTilesLogicType'
import {
    getOrderBy,
    getSortedColumnsByArray,
    isDraftConversionGoalColumn,
    orderArrayByPreference,
    rawColumnsForTiles,
    validColumnsForTiles,
} from './utils'

export const MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID = 'marketing-analytics'

const isSchemaBackedMarketingColumn = (column: validColumnsForTiles): column is rawColumnsForTiles =>
    column !== 'roas' && column !== 'cost_per_reported_conversion'

// Maps a chart column to a HogQL aggregate over the native cost precompute table. Costs are already
// converted to the team's base currency at materialization time, so no convertCurrency() is needed.
const PRECOMPUTE_METRIC_EXPR: Record<validColumnsForTiles, string> = {
    cost: 'sum(cost)',
    clicks: 'sum(clicks)',
    impressions: 'sum(impressions)',
    reported_conversion: 'sum(reported_conversions)',
    reported_conversion_value: 'sum(reported_conversion_value)',
    roas: 'sum(reported_conversion_value) / nullIf(sum(cost), 0)',
    cost_per_reported_conversion: 'sum(cost) / nullIf(sum(reported_conversions), 0)',
}

const createInsightProps = (tile: TileId, tab?: string): InsightLogicProps => ({
    dashboardItemId: getDashboardItemId(tile, tab, false),
    loadPriority: loadPriorityMap[tile],
    dataNodeCollectionId: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
})

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
        // One selector per tile so an input change only invalidates the tile that uses
        // it — entries keep identity in `tiles` below, so `dataNodeLogic` doesn't refetch.
        overviewTile: [
            (s) => [s.compareFilter, s.dateFilter, s.draftConversionGoal, s.integrationFilter],
            (
                compareFilter: CompareFilter | null,
                dateFilter: { dateFrom: string | null; dateTo: string | null; interval: IntervalType },
                draftConversionGoal: ConversionGoalFilter | null,
                integrationFilter: IntegrationFilter
            ): QueryTile => ({
                kind: 'query',
                tileId: TileId.MARKETING_OVERVIEW,
                layout: {
                    colSpanClassName: 'md:col-span-2 2xl:col-span-3' as `md:col-span-${number}`,
                    orderWhenLargeClassName: '2xl:order-0',
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
                    tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
                },
                insightProps: createInsightProps(TileId.MARKETING_OVERVIEW),
                canOpenInsight: false,
            }),
        ],
        marketingChartTile: [
            (s) => [
                s.compareFilter,
                s.dateFilter,
                s.createMarketingDataWarehouseNodes,
                s.chartDisplayType,
                s.tileColumnSelection,
                s.baseCurrency,
                s.integrationFilter,
            ],
            (
                compareFilter: CompareFilter | null,
                dateFilter: { dateFrom: string | null; dateTo: string | null; interval: IntervalType },
                createMarketingDataWarehouseNodes: DataWarehouseNode[],
                chartDisplayType: ChartDisplayType,
                tileColumnSelection: validColumnsForTiles,
                baseCurrency: CurrencyCode,
                integrationFilter: IntegrationFilter
            ): QueryTile => {
                const tileColumnSelectionName = tileColumnSelection?.split('_').join(' ')
                const hasSources = createMarketingDataWarehouseNodes.length > 0
                const metricExpr = PRECOMPUTE_METRIC_EXPR[tileColumnSelection] ?? 'sum(cost)'
                const isCurrency =
                    tileColumnSelection && isSchemaBackedMarketingColumn(tileColumnSelection)
                        ? MARKETING_ANALYTICS_SCHEMA[tileColumnSelection].isCurrency
                        : false
                const { symbol: currencySymbol, isPrefix: currencyIsPrefix } = getCurrencySymbol(baseCurrency)

                // Read costs from the native precompute table via a DataWarehouseNode series — TrendsQuery
                // then gives us compare, per-source breakdown and currency formatting for free, while the
                // read stays off S3. `grain = 'campaign'` avoids double-counting the ad-group/ad grains;
                // `expires_at > today()` keeps only fresh rows. The table exposes a virtual `timestamp`
                // (cost_date as DateTime) so a DataWarehouseNode can target it.
                const selectedSourceIds = integrationFilter.integrationSourceIds || []
                const sourceClause =
                    selectedSourceIds.length > 0
                        ? ` AND source_id IN (${selectedSourceIds.map((id) => `'${id}'`).join(', ')})`
                        : ''
                const costSeriesNode: DataWarehouseNode = {
                    kind: NodeKind.DataWarehouseNode,
                    id: 'marketing_costs_preaggregated',
                    name: tileColumnSelectionName,
                    custom_name: tileColumnSelectionName,
                    table_name: 'posthog.marketing_costs_preaggregated',
                    id_field: 'campaign_id',
                    distinct_id_field: 'campaign_id',
                    timestamp_field: 'timestamp',
                    math: HogQLMathType.HogQL,
                    math_hogql: metricExpr,
                    properties: [
                        {
                            type: PropertyFilterType.HogQL,
                            key: `grain = 'campaign' AND expires_at > today()${sourceClause}`,
                        },
                    ],
                }
                const chartQuery: QueryTile['query'] = {
                    kind: NodeKind.InsightVizNode,
                    embedded: true,
                    hidePersonsModal: true,
                    hideTooltipOnScroll: true,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: hasSources
                            ? [costSeriesNode]
                            : [
                                  {
                                      kind: NodeKind.EventsNode,
                                      event: 'no_sources_configured',
                                      custom_name: 'No marketing sources configured',
                                      math: BaseMathType.TotalCount,
                                  },
                              ],
                        compareFilter: compareFilter || undefined,
                        breakdownFilter: hasSources
                            ? { breakdowns: [{ type: 'data_warehouse', property: 'source_name' }] }
                            : undefined,
                        interval: dateFilter.interval,
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        trendsFilter: {
                            display: chartDisplayType,
                            aggregationAxisFormat: 'numeric',
                            aggregationAxisPrefix: isCurrency && currencyIsPrefix ? currencySymbol : undefined,
                            aggregationAxisPostfix: isCurrency && !currencyIsPrefix ? ` ${currencySymbol}` : undefined,
                        },
                        tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                }
                return {
                    kind: 'query',
                    tileId: TileId.MARKETING,
                    layout: {
                        colSpanClassName: 'md:col-span-2',
                        orderWhenLargeClassName: '2xl:order-1',
                    },
                    title: `Marketing ${tileColumnSelectionName}`,
                    query: chartQuery,
                    showIntervalSelect: true,
                    insightProps: createInsightProps(TileId.MARKETING, `${chartDisplayType}-${tileColumnSelection}`),
                    canOpenInsight: true,
                    canOpenModal: false,
                    docs: {
                        title: `Marketing ${tileColumnSelectionName}`,
                        description:
                            createMarketingDataWarehouseNodes.length > 0
                                ? `Track ${tileColumnSelectionName || 'costs'} from your configured marketing data sources.`
                                : `Configure marketing data sources in the settings to track ${tileColumnSelectionName || 'costs'} from your ad platforms.`,
                    },
                }
            },
        ],
        campaignBreakdownTile: [
            (s) => [s.campaignCostsBreakdown, s.drillDownLevel],
            (
                campaignCostsBreakdown: DataTableNode | null,
                drillDownLevel: MarketingAnalyticsDrillDownLevel
            ): QueryTile | null =>
                campaignCostsBreakdown
                    ? {
                          kind: 'query',
                          tileId: TileId.MARKETING_CAMPAIGN_BREAKDOWN,
                          layout: {
                              colSpanClassName: 'md:col-span-2',
                              orderWhenLargeClassName: '2xl:order-2',
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
        ],
        tiles: [
            (s) => [s.overviewTile, s.marketingChartTile, s.campaignBreakdownTile],
            (
                overviewTile: QueryTile,
                marketingChartTile: QueryTile,
                campaignBreakdownTile: QueryTile | null
            ): QueryTile[] => [overviewTile, marketingChartTile, campaignBreakdownTile].filter(isNotNil) as QueryTile[],
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
