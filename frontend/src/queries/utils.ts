import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { MAX_DEFAULT_PROPORTION_LEGEND_PARTS, PERCENT_STACK_VIEW_DISPLAY_TYPE } from 'lib/constants'
import { escapePropertyAsHogQLIdentifier, isQuoted } from 'lib/utils/hogql'

import { ProductAnalyticsInsightNodeKind } from '~/queries/nodes/InsightQuery/defaults'
import { getDisplay, getBreakdown } from '~/queries/schema/node-accessors'
import {
    isNodeWithSource,
    isEventsNode,
    isActionsNode,
    isDataWarehouseNode,
    isPersonsNode,
    isActorsQuery,
    isDataTableNode,
    isDataTableNodeWithHogQLQuery,
    isDataVisualizationNode,
    isInsightVizNode,
    isHogQLQuery,
    isWebOverviewQuery,
    isWebStatsTableQuery,
    isTrendsQuery,
    isFunnelsQuery,
    isRetentionQuery,
    isStickinessQuery,
    isLifecycleQuery,
    isInsightQueryNode,
    hasBreakdownFilter,
} from '~/queries/schema/node-guards'
import {
    AccountsQuery,
    AccountsTableQuery,
    ActorsQuery,
    DataVisualizationNode,
    DataWarehouseSourceUsage,
    DatabaseSchemaQuery,
    EndpointsUsageOverviewQuery,
    EndpointsUsageTableQuery,
    EndpointsUsageTrendsQuery,
    ErrorTrackingIssueCorrelationQuery,
    ErrorTrackingIssueEventsQuery,
    ErrorTrackingQuery,
    EventsQuery,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    FunnelsQuery,
    GoalLine,
    GroupsQuery,
    HogQLMetadata,
    HogQLQuery,
    HogQuery,
    InsightActorsQuery,
    InsightFilter,
    InsightFilterProperty,
    InsightQueryNode,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsTableQuery,
    MathType,
    MetricsHistogramQuery,
    Node,
    NodeKind,
    PersonsNode,
    ProductAnalyticsInsightQueryNode,
    QuerySchema,
    QueryStatusResponse,
    ResultCustomizationBy,
    ResultCustomizationByPosition,
    ResultCustomizationByValue,
    RetentionQuery,
    SavedInsightNode,
    SessionAttributionExplorerQuery,
    SessionQuery,
    SessionsQuery,
    StickinessQuery,
    TracesQuery,
    TrendsFormulaNode,
    TrendsQuery,
    WebGoalsQuery,
    WebNotableChangesQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebVitalsPathBreakdownQuery,
    WebVitalsQuery,
} from '~/queries/schema/schema-general'
import { AnnotationScope, BaseMathType, ChartDisplayType, GroupTypeIndex } from '~/types'

export function isDataNode(node?: Record<string, any> | null): node is EventsQuery | PersonsNode {
    return (
        isEventsNode(node) ||
        isActionsNode(node) ||
        isPersonsNode(node) ||
        isEventsQuery(node) ||
        isActorsQuery(node) ||
        isHogQLQuery(node) ||
        isHogQLMetadata(node)
    )
}

export function isEventsQuery(node?: Record<string, any> | null): node is EventsQuery {
    return node?.kind === NodeKind.EventsQuery
}

export function isSessionsQuery(node?: Record<string, any> | null): node is SessionsQuery {
    return node?.kind === NodeKind.SessionsQuery
}

export function isInsightActorsQuery(node?: Record<string, any> | null): node is InsightActorsQuery {
    return node?.kind === NodeKind.InsightActorsQuery
}

export function convertDataTableNodeToDataVisualizationNode(node: Node | null): Node | null {
    if (!isDataTableNodeWithHogQLQuery(node)) {
        return node
    }

    const {
        kind: _kind,
        source,
        columns,
        hiddenColumns: legacyHiddenColumns,
        pinnedColumns: legacyPinnedColumns,
        ...rest
    } = node
    const hiddenColumns = new Set(legacyHiddenColumns ?? [])
    const visibleColumns = columns?.filter((column) => !hiddenColumns.has(column))
    const tableSettingsColumns = visibleColumns?.length ? visibleColumns.map((column) => ({ column })) : undefined
    const pinnedColumns = legacyPinnedColumns?.filter((column) => !hiddenColumns.has(column))
    const mappedTableSettings =
        tableSettingsColumns || pinnedColumns?.length
            ? {
                  ...(tableSettingsColumns ? { columns: tableSettingsColumns } : {}),
                  ...(pinnedColumns?.length ? { pinnedColumns } : {}),
              }
            : undefined
    const tableSettings = {
        ...(rest as Partial<DataVisualizationNode>).tableSettings,
        ...mappedTableSettings,
    }

    return {
        ...rest,
        kind: NodeKind.DataVisualizationNode,
        source: source as HogQLQuery,
        display: ChartDisplayType.ActionsTable,
        ...(Object.keys(tableSettings).length ? { tableSettings } : {}),
    } as DataVisualizationNode
}

export function isSavedInsightNode(node?: Record<string, any> | null): node is SavedInsightNode {
    return node?.kind === NodeKind.SavedInsightNode
}

export function isHogQuery(node?: Record<string, any> | null): node is HogQuery {
    return node?.kind === NodeKind.HogQuery
}

export function isHogQLMetadata(node?: Record<string, any> | null): node is HogQLMetadata {
    return node?.kind === NodeKind.HogQLMetadata
}

export function isMetricsHistogramQuery(node?: Record<string, any> | null): node is MetricsHistogramQuery {
    return node?.kind === NodeKind.MetricsHistogramQuery
}

export function isEndpointsUsageOverviewQuery(node?: Record<string, any> | null): node is EndpointsUsageOverviewQuery {
    return node?.kind === NodeKind.EndpointsUsageOverviewQuery
}

export function isEndpointsUsageTableQuery(node?: Record<string, any> | null): node is EndpointsUsageTableQuery {
    return node?.kind === NodeKind.EndpointsUsageTableQuery
}

export function isEndpointsUsageTrendsQuery(node?: Record<string, any> | null): node is EndpointsUsageTrendsQuery {
    return node?.kind === NodeKind.EndpointsUsageTrendsQuery
}

export function isEndpointsUsageQuery(
    node?: Record<string, any> | null
): node is EndpointsUsageOverviewQuery | EndpointsUsageTableQuery | EndpointsUsageTrendsQuery {
    return isEndpointsUsageOverviewQuery(node) || isEndpointsUsageTableQuery(node) || isEndpointsUsageTrendsQuery(node)
}

export function isWebAnalyticsInsightQuery(
    node?: Record<string, any> | null
): node is WebStatsTableQuery | WebOverviewQuery {
    return isWebStatsTableQuery(node) || isWebOverviewQuery(node)
}

export function isWebExternalClicksQuery(node?: Record<string, any> | null): boolean {
    return node?.kind === NodeKind.WebExternalClicksTableQuery
}

export function isWebBotsTableQuery(node?: Record<string, any> | null): boolean {
    return node?.kind === NodeKind.WebBotsTableQuery
}

export function isWebGoalsQuery(node?: Record<string, any> | null): node is WebGoalsQuery {
    return node?.kind === NodeKind.WebGoalsQuery
}

export function isWebNotableChangesQuery(node?: Record<string, any> | null): node is WebNotableChangesQuery {
    return node?.kind === NodeKind.WebNotableChangesQuery
}

export function isMarketingAnalyticsTableQuery(
    node?: Record<string, any> | null
): node is MarketingAnalyticsTableQuery {
    return node?.kind === NodeKind.MarketingAnalyticsTableQuery
}

export function isMarketingAnalyticsAggregatedQuery(
    node?: Record<string, any> | null
): node is MarketingAnalyticsAggregatedQuery {
    return node?.kind === NodeKind.MarketingAnalyticsAggregatedQuery
}

export function isTracesQuery(node?: Record<string, any> | null): node is TracesQuery {
    return node?.kind === NodeKind.TracesQuery
}

export function isSessionQuery(node?: Record<string, any> | null): node is SessionQuery {
    return node?.kind === NodeKind.SessionQuery
}

export function isWebVitalsQuery(node?: Record<string, any> | null): node is WebVitalsQuery {
    return node?.kind === NodeKind.WebVitalsQuery
}

export function isWebVitalsPathBreakdownQuery(node?: Record<string, any> | null): node is WebVitalsPathBreakdownQuery {
    return node?.kind === NodeKind.WebVitalsPathBreakdownQuery
}

export function isSessionAttributionExplorerQuery(
    node?: Record<string, any> | null
): node is SessionAttributionExplorerQuery {
    return node?.kind === NodeKind.SessionAttributionExplorerQuery
}

export function isErrorTrackingQuery(node?: Record<string, any> | null): node is ErrorTrackingQuery {
    return node?.kind === NodeKind.ErrorTrackingQuery
}

export function isExperimentMetric(
    metric: ExperimentMetric | ExperimentFunnelsQuery | ExperimentTrendsQuery
): metric is ExperimentMetric {
    return metric.kind === NodeKind.ExperimentMetric
}

export function isErrorTrackingIssueCorrelationQuery(
    node?: Record<string, any> | null
): node is ErrorTrackingIssueCorrelationQuery {
    return node?.kind === NodeKind.ErrorTrackingIssueCorrelationQuery
}

export function isErrorTrackingIssueEventsQuery(
    node?: Record<string, any> | null
): node is ErrorTrackingIssueEventsQuery {
    return node?.kind === NodeKind.ErrorTrackingIssueEventsQuery
}

export function isInsightQueryWithDisplay(
    node?: Record<string, any> | null
): node is TrendsQuery | RetentionQuery | StickinessQuery {
    return isTrendsQuery(node) || isStickinessQuery(node) || isRetentionQuery(node)
}

export function isDatabaseSchemaQuery(node?: Node): node is DatabaseSchemaQuery {
    return node?.kind === NodeKind.DatabaseSchemaQuery
}

export function isQueryForGroup(query: PersonsNode | ActorsQuery): boolean {
    return (
        isActorsQuery(query) &&
        isInsightActorsQuery(query.source) &&
        isRetentionQuery(query.source.source) &&
        query.source.source.aggregation_group_type_index != null
    )
}

export function isAsyncResponse(response: NonNullable<QuerySchema['response']>): response is QueryStatusResponse {
    return 'query_status' in response && response.query_status
}

export function shouldQueryBeAsync(query: Node): boolean {
    return (
        isInsightQueryNode(query) ||
        isHogQLQuery(query) ||
        isTracesQuery(query) ||
        isSessionQuery(query) ||
        (isDataTableNode(query) &&
            (isInsightQueryNode(query.source) || isTracesQuery(query.source) || isSessionQuery(query.source))) ||
        (isDataVisualizationNode(query) &&
            (isInsightQueryNode(query.source) || isTracesQuery(query.source) || isSessionQuery(query.source)))
    )
}

export const isMetricInsightQuery = (query?: Record<string, any> | null): boolean =>
    (isDataVisualizationNode(query) && query.display === ChartDisplayType.Metric) ||
    (isInsightVizNode(query) && isTrendsQuery(query.source) && getDisplay(query.source) === ChartDisplayType.Metric)

export const getFormulas = (query: InsightQueryNode | null): string[] | undefined => {
    if (isTrendsQuery(query)) {
        return (
            query.trendsFilter?.formulaNodes?.map((node) => node.formula) ||
            query.trendsFilter?.formulas ||
            (query.trendsFilter?.formula ? [query.trendsFilter.formula] : undefined)
        )
    }
    return undefined
}

export const getFormulaNodes = (query: InsightQueryNode | null): TrendsFormulaNode[] | undefined => {
    if (isTrendsQuery(query)) {
        return (
            query.trendsFilter?.formulaNodes ||
            query.trendsFilter?.formulas?.map((formula) => ({ formula })) ||
            (query.trendsFilter?.formula ? [{ formula: query.trendsFilter.formula }] : undefined)
        )
    }
    return undefined
}

/** Extract the connector-synced warehouse sources a query touched from its response, if the
 * backend populated them (currently HogQL / SQL-editor responses). Always returns an array. */
export function dataWarehouseSourcesFromResponse(response: unknown): DataWarehouseSourceUsage[] {
    if (response && typeof response === 'object' && Array.isArray((response as any).used_data_warehouse_sources)) {
        return (response as any).used_data_warehouse_sources
    }
    return []
}

export const getAggregationGroupTypeIndex = (query: InsightQueryNode): GroupTypeIndex | null | undefined => {
    if (!isStickinessQuery(query) && 'aggregation_group_type_index' in query) {
        return query.aggregation_group_type_index as GroupTypeIndex | null | undefined
    }
    return undefined
}

const isProportionBarQuery = (query: TrendsQuery): boolean =>
    query.trendsFilter?.display === ChartDisplayType.ActionsProportionBar

export const getShowLegend = (query: InsightQueryNode, partCount?: number): boolean | undefined => {
    if (isStickinessQuery(query)) {
        return query.stickinessFilter?.showLegend
    } else if (isTrendsQuery(query)) {
        const showsByDefault =
            isProportionBarQuery(query) && partCount !== undefined && partCount <= MAX_DEFAULT_PROPORTION_LEGEND_PARTS
        return query.trendsFilter?.showLegend ?? (showsByDefault ? true : undefined)
    } else if (isLifecycleQuery(query)) {
        return query.lifecycleFilter?.showLegend
    } else if (isFunnelsQuery(query)) {
        return query.funnelsFilter?.showLegend
    }
    return undefined
}

// Widened to `string` (not the literal union) to match getYAxisScaleType — kea-typegen can't
// serialize an inline string-literal union and emits a broken type; consumers narrow as needed.
export const getLegendPosition = (query: InsightQueryNode): string | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.legendPosition ?? (isProportionBarQuery(query) ? 'bottom' : undefined)
    } else if (isStickinessQuery(query)) {
        return query.stickinessFilter?.legendPosition
    } else if (isLifecycleQuery(query)) {
        return query.lifecycleFilter?.legendPosition
    } else if (isFunnelsQuery(query)) {
        return query.funnelsFilter?.legendPosition
    }
    return undefined
}

export const getShowAlertThresholdLines = (query: InsightQueryNode): boolean | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.showAlertThresholdLines
    }
    return undefined
}

export const getShowAnnotations = (query: InsightQueryNode): boolean | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.showAnnotations
    } else if (isFunnelsQuery(query)) {
        return query.funnelsFilter?.showAnnotations
    }
    return undefined
}

export const getAnnotationsScope = (query: InsightQueryNode): AnnotationScope | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.annotationsScope
    } else if (isFunnelsQuery(query)) {
        return query.funnelsFilter?.annotationsScope
    }
    return undefined
}

export const getShowLabelsOnSeries = (query: InsightQueryNode): boolean | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.showLabelsOnSeries
    }
    return undefined
}

export const getShowValuesOnSeries = (query: InsightQueryNode): boolean | undefined => {
    if (isLifecycleQuery(query)) {
        return query.lifecycleFilter?.showValuesOnSeries
    } else if (isStickinessQuery(query)) {
        return query.stickinessFilter?.showValuesOnSeries
    } else if (isTrendsQuery(query)) {
        return query.trendsFilter?.showValuesOnSeries
    } else if (isFunnelsQuery(query)) {
        return query.funnelsFilter?.showValuesOnSeries
    }
    return undefined
}

export const getShowPercentagesOnSeries = (query: InsightQueryNode): boolean | undefined => {
    if (isLifecycleQuery(query)) {
        return query.lifecycleFilter?.showPercentagesOnSeries
    }
    return undefined
}

export const getYAxisScaleType = (query: InsightQueryNode): string | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.yAxisScaleType
    }
    return undefined
}

export const getShowMultipleYAxes = (query: InsightQueryNode): boolean | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.showMultipleYAxes
    } else if (isStickinessQuery(query)) {
        return query.stickinessFilter?.showMultipleYAxes
    }
    return undefined
}

export const getResultCustomizationBy = (query: InsightQueryNode): ResultCustomizationBy | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.resultCustomizationBy
    } else if (isStickinessQuery(query)) {
        return query.stickinessFilter?.resultCustomizationBy
    }
    return undefined
}

export function getResultCustomizations(query: FunnelsQuery): Record<string, ResultCustomizationByValue> | undefined
export function getResultCustomizations(
    query: TrendsQuery | StickinessQuery
): Record<number, ResultCustomizationByPosition> | undefined
export function getResultCustomizations(
    query: InsightQueryNode
): Record<string, ResultCustomizationByValue> | Record<number, ResultCustomizationByPosition> | undefined
export function getResultCustomizations(
    query: InsightQueryNode
): Record<string, ResultCustomizationByValue> | Record<number, ResultCustomizationByPosition> | undefined {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.resultCustomizations
    } else if (isStickinessQuery(query)) {
        return query.stickinessFilter?.resultCustomizations
    } else if (isFunnelsQuery(query)) {
        return query.funnelsFilter?.resultCustomizations
    }
    return undefined
}

export const getGoalLines = (query: InsightQueryNode): GoalLine[] | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.goalLines
    } else if (isFunnelsQuery(query)) {
        return query.funnelsFilter?.goalLines
    } else if (isRetentionQuery(query)) {
        return query.retentionFilter?.goalLines
    }

    return undefined
}

export const supportsPercentStackView = (q: InsightQueryNode | null | undefined): boolean =>
    isTrendsQuery(q) && PERCENT_STACK_VIEW_DISPLAY_TYPE.includes(getDisplay(q) || ChartDisplayType.ActionsLineGraph)

export const getShowPercentStackView = (query: InsightQueryNode): boolean | undefined =>
    supportsPercentStackView(query) && (query as TrendsQuery)?.trendsFilter?.showPercentStackView

export const supportsBarValueStacking = (q: InsightQueryNode | null | undefined): boolean =>
    isTrendsQuery(q) && getDisplay(q) === ChartDisplayType.ActionsBarValue && hasBreakdownFilter(getBreakdown(q))

export const getStackBreakdownValues = (query: InsightQueryNode): boolean | undefined =>
    supportsBarValueStacking(query) && (query as TrendsQuery)?.trendsFilter?.stackBreakdownValues

export const nodeKindToFilterProperty: Record<ProductAnalyticsInsightNodeKind, InsightFilterProperty> = {
    [NodeKind.TrendsQuery]: 'trendsFilter',
    [NodeKind.FunnelsQuery]: 'funnelsFilter',
    [NodeKind.RetentionQuery]: 'retentionFilter',
    [NodeKind.PathsQuery]: 'pathsFilter',
    [NodeKind.PathsV2Query]: 'pathsV2Filter',
    [NodeKind.StickinessQuery]: 'stickinessFilter',
    [NodeKind.LifecycleQuery]: 'lifecycleFilter',
}

export function filterKeyForQuery(node: ProductAnalyticsInsightQueryNode): InsightFilterProperty {
    return nodeKindToFilterProperty[node.kind]
}

export function filterForQuery(node: ProductAnalyticsInsightQueryNode): InsightFilter | undefined {
    const filterProperty = nodeKindToFilterProperty[node.kind]
    return node[filterProperty as keyof InsightQueryNode] as InsightFilter | undefined
}

export function trimQuotes(identifier: string): string {
    if (isQuoted(identifier)) {
        return identifier.slice(1, -1)
    }
    return identifier
}

export function taxonomicEventFilterToHogQL(
    groupType: TaxonomicFilterGroupType,
    value: TaxonomicFilterValue
): string | null {
    if (groupType === TaxonomicFilterGroupType.EventProperties) {
        return `properties.${escapePropertyAsHogQLIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.PersonProperties) {
        return `person.properties.${escapePropertyAsHogQLIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.EventFeatureFlags) {
        return `properties.${escapePropertyAsHogQLIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.SessionProperties) {
        return `session.${escapePropertyAsHogQLIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.HogQLExpression && value) {
        return String(value)
    }
    return null
}

export function taxonomicPersonFilterToHogQL(
    groupType: TaxonomicFilterGroupType,
    value: TaxonomicFilterValue
): string | null {
    if (groupType === TaxonomicFilterGroupType.PersonProperties) {
        return `properties.${escapePropertyAsHogQLIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.HogQLExpression && value) {
        return String(value)
    }
    return null
}

export function taxonomicSessionFilterToHogQL(
    groupType: TaxonomicFilterGroupType,
    value: TaxonomicFilterValue
): string | null {
    if (groupType === TaxonomicFilterGroupType.SessionProperties) {
        return `session.${escapePropertyAsHogQLIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.PersonProperties) {
        return `person.properties.${escapePropertyAsHogQLIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.HogQLExpression && value) {
        return String(value)
    }
    // Event-scoped picks (e.g. a suggested or recent event property) have no
    // equivalent on the sessions table — adding one would fail resolution.
    return null
}

export function taxonomicGroupFilterToHogQL(
    groupType: TaxonomicFilterGroupType,
    value: TaxonomicFilterValue
): string | null {
    if (groupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix)) {
        return `properties.${escapePropertyAsHogQLIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.HogQLExpression && value) {
        return String(value)
    }
    return null
}

export function isHogQLAggregation(hogQl: string): boolean {
    return (
        hogQl.includes('count(') ||
        hogQl.includes('any(') ||
        hogQl.includes('sum(') ||
        hogQl.includes('avg(') ||
        hogQl.includes('min(') ||
        hogQl.includes('max(')
    )
}

export function isValidQueryForExperiment(query: Node): boolean {
    if (!isNodeWithSource(query) || !isFunnelsQuery(query.source)) {
        return false
    }

    const { series } = query.source
    return series.length >= 2 && !series?.some((node) => isDataWarehouseNode(node))
}

export function isGroupsQuery(node?: Record<string, any> | null): node is GroupsQuery {
    return node?.kind === NodeKind.GroupsQuery
}

export function isAccountsQuery(node?: Record<string, any> | null): node is AccountsQuery {
    return node?.kind === NodeKind.AccountsQuery
}

export function isAccountsTableQuery(node?: Record<string, any> | null): node is AccountsTableQuery {
    return node?.kind === NodeKind.AccountsTableQuery
}

export const TRAILING_MATH_TYPES = new Set<MathType>([BaseMathType.WeeklyActiveUsers, BaseMathType.MonthlyActiveUsers])

/**
 * Determines if a math type should display a warning based on the trends query interval and display category
 */
export function getMathTypeWarning(
    key: MathType,
    query: Record<string, any>,
    isTotalValue: boolean
): null | 'total' | 'monthly' | 'weekly' {
    let warning: null | 'total' | 'monthly' | 'weekly' = null

    if (isInsightVizNode(query) && isTrendsQuery(query.source) && TRAILING_MATH_TYPES.has(key)) {
        const trendsQuery = query.source
        const interval = trendsQuery?.interval || 'day'
        const isWeekOrLongerInterval = interval === 'week' || interval === 'month'
        const isMonthOrLongerInterval = interval === 'month'

        if (key === BaseMathType.MonthlyActiveUsers && isMonthOrLongerInterval) {
            warning = 'monthly'
        } else if (key === BaseMathType.WeeklyActiveUsers && isWeekOrLongerInterval) {
            warning = 'weekly'
        } else if (isTotalValue) {
            warning = 'total'
        }
    }

    return warning
}
