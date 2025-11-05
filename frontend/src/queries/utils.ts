import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { PERCENT_STACK_VIEW_DISPLAY_TYPE } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { getAppContext } from 'lib/utils/getAppContext'

import {
    ActionsNode,
    ActorsQuery,
    BreakdownFilter,
    CompareFilter,
    DataTableNode,
    DataVisualizationNode,
    DataWarehouseNode,
    DatabaseSchemaQuery,
    DateRange,
    ErrorTrackingIssueCorrelationQuery,
    ErrorTrackingQuery,
    EventsNode,
    EventsQuery,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    FunnelsQuery,
    GoalLine,
    GroupsQuery,
    HogQLASTQuery,
    HogQLMetadata,
    HogQLQuery,
    HogQuery,
    InsightActorsQuery,
    InsightFilter,
    InsightFilterProperty,
    InsightNodeKind,
    InsightQueryNode,
    InsightVizNode,
    LifecycleQuery,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsTableQuery,
    MathType,
    Node,
    NodeKind,
    PathsQuery,
    PersonsNode,
    QuerySchema,
    QueryStatusResponse,
    ResultCustomizationBy,
    ResultCustomizationByPosition,
    ResultCustomizationByValue,
    RetentionQuery,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsTopCustomersQuery,
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleEventsQuery,
    SavedInsightNode,
    SessionAttributionExplorerQuery,
    StickinessQuery,
    TracesQuery,
    TrendsFormulaNode,
    TrendsQuery,
    WebGoalsQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebTrendsQuery,
    WebVitalsPathBreakdownQuery,
    WebVitalsQuery,
} from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, IntervalType } from '~/types'

import { LATEST_VERSIONS } from './latest-versions'

export function isDataNode(node?: Record<string, any> | null): node is EventsQuery | PersonsNode {
    return (
        isEventsNode(node) ||
        isActionsNode(node) ||
        isPersonsNode(node) ||
        isEventsQuery(node) ||
        isActorsQuery(node) ||
        isHogQLQuery(node) ||
        isHogQLASTQuery(node) ||
        isHogQLMetadata(node)
    )
}

export function isNodeWithSource(node?: Record<string, any> | null): node is DataTableNode | InsightVizNode {
    if (!node) {
        return false
    }

    return isDataTableNode(node) || isDataVisualizationNode(node) || isInsightVizNode(node)
}

export function isEventsNode(node?: Record<string, any> | null): node is EventsNode {
    return node?.kind === NodeKind.EventsNode
}

export function isEventsQuery(node?: Record<string, any> | null): node is EventsQuery {
    return node?.kind === NodeKind.EventsQuery
}

export function isActionsNode(node?: Record<string, any> | null): node is ActionsNode {
    return node?.kind === NodeKind.ActionsNode
}

export function isDataWarehouseNode(node?: Record<string, any> | null): node is DataWarehouseNode {
    return node?.kind === NodeKind.DataWarehouseNode
}

/** @deprecated `ActorsQuery` is now used instead of `PersonsNode`. */
export function isPersonsNode(node?: Record<string, any> | null): node is PersonsNode {
    return node?.kind === NodeKind.PersonsNode
}

export function isActorsQuery(node?: Record<string, any> | null): node is ActorsQuery {
    return node?.kind === NodeKind.ActorsQuery
}

export function isInsightActorsQuery(node?: Record<string, any> | null): node is InsightActorsQuery {
    return node?.kind === NodeKind.InsightActorsQuery
}

export function isDataTableNode(node?: Record<string, any> | null): node is DataTableNode {
    return node?.kind === NodeKind.DataTableNode
}

/** Previously SQL queries by default were `DataTableNode`s. However now new SQL queries are `DataVisualizationNode`s */
export function isDataTableNodeWithHogQLQuery(node?: Record<string, any> | null): node is DataTableNode & {
    source: HogQLQuery
} {
    return isDataTableNode(node) && isHogQLQuery(node.source)
}

export function isDataVisualizationNode(node?: Record<string, any> | null): node is DataVisualizationNode {
    return node?.kind === NodeKind.DataVisualizationNode
}

export function isSavedInsightNode(node?: Record<string, any> | null): node is SavedInsightNode {
    return node?.kind === NodeKind.SavedInsightNode
}

export function isInsightVizNode(node?: Record<string, any> | null): node is InsightVizNode {
    return node?.kind === NodeKind.InsightVizNode
}

export function isHogQuery(node?: Record<string, any> | null): node is HogQuery {
    return node?.kind === NodeKind.HogQuery
}

export function isHogQLQuery(node?: Record<string, any> | null): node is HogQLQuery {
    return node?.kind === NodeKind.HogQLQuery
}

export function isHogQLASTQuery(node?: Record<string, any> | null): node is HogQLASTQuery {
    return node?.kind === NodeKind.HogQLASTQuery
}

export function isHogQLMetadata(node?: Record<string, any> | null): node is HogQLMetadata {
    return node?.kind === NodeKind.HogQLMetadata
}

export function isRevenueAnalyticsGrossRevenueQuery(
    node?: Record<string, any> | null
): node is RevenueAnalyticsGrossRevenueQuery {
    return node?.kind === NodeKind.RevenueAnalyticsGrossRevenueQuery
}

export function isRevenueAnalyticsMetricsQuery(
    node?: Record<string, any> | null
): node is RevenueAnalyticsMetricsQuery {
    return node?.kind === NodeKind.RevenueAnalyticsMetricsQuery
}

export function isRevenueAnalyticsMRRQuery(node?: Record<string, any> | null): node is RevenueAnalyticsMRRQuery {
    return node?.kind === NodeKind.RevenueAnalyticsMRRQuery
}

export function isRevenueAnalyticsOverviewQuery(
    node?: Record<string, any> | null
): node is RevenueAnalyticsOverviewQuery {
    return node?.kind === NodeKind.RevenueAnalyticsOverviewQuery
}

export function isRevenueAnalyticsTopCustomersQuery(
    node?: Record<string, any> | null
): node is RevenueAnalyticsTopCustomersQuery {
    return node?.kind === NodeKind.RevenueAnalyticsTopCustomersQuery
}

export function isWebOverviewQuery(node?: Record<string, any> | null): node is WebOverviewQuery {
    return node?.kind === NodeKind.WebOverviewQuery
}

export function isWebStatsTableQuery(node?: Record<string, any> | null): node is WebStatsTableQuery {
    return node?.kind === NodeKind.WebStatsTableQuery
}

export function isWebExternalClicksQuery(node?: Record<string, any> | null): boolean {
    return node?.kind === NodeKind.WebExternalClicksTableQuery
}

export function isWebGoalsQuery(node?: Record<string, any> | null): node is WebGoalsQuery {
    return node?.kind === NodeKind.WebGoalsQuery
}

export function isWebTrendsQuery(node?: Record<string, any> | null): node is WebTrendsQuery {
    return node?.kind === NodeKind.WebTrendsQuery
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

export function isRevenueExampleEventsQuery(node?: Record<string, any> | null): node is RevenueExampleEventsQuery {
    return node?.kind === NodeKind.RevenueExampleEventsQuery
}

export function isRevenueExampleDataWarehouseTablesQuery(
    node?: Record<string, any> | null
): node is RevenueExampleDataWarehouseTablesQuery {
    return node?.kind === NodeKind.RevenueExampleDataWarehouseTablesQuery
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

export function containsHogQLQuery(node?: Record<string, any> | null): boolean {
    if (!node) {
        return false
    }
    return isHogQLQuery(node) || (isNodeWithSource(node) && isHogQLQuery(node.source))
}

/*
 * Insight Queries
 */

export function isTrendsQuery(node?: Record<string, any> | null): node is TrendsQuery {
    return node?.kind === NodeKind.TrendsQuery
}

export function isFunnelsQuery(node?: Record<string, any> | null): node is FunnelsQuery {
    return node?.kind === NodeKind.FunnelsQuery
}

export function isRetentionQuery(node?: Record<string, any> | null): node is RetentionQuery {
    return node?.kind === NodeKind.RetentionQuery
}

export function isPathsQuery(node?: Record<string, any> | null): node is PathsQuery {
    return node?.kind === NodeKind.PathsQuery
}

export function isStickinessQuery(node?: Record<string, any> | null): node is StickinessQuery {
    return node?.kind === NodeKind.StickinessQuery
}

export function isLifecycleQuery(node?: Record<string, any> | null): node is LifecycleQuery {
    return node?.kind === NodeKind.LifecycleQuery
}

export function isInsightQueryWithDisplay(node?: Record<string, any> | null): node is TrendsQuery | StickinessQuery {
    return isTrendsQuery(node) || isStickinessQuery(node)
}

export function isInsightQueryWithBreakdown(node?: Record<string, any> | null): node is TrendsQuery | FunnelsQuery {
    return isTrendsQuery(node) || isFunnelsQuery(node) || isRetentionQuery(node)
}

export function isInsightQueryWithCompare(node?: Record<string, any> | null): node is TrendsQuery | StickinessQuery {
    return isTrendsQuery(node) || isStickinessQuery(node)
}

export function isDatabaseSchemaQuery(node?: Node): node is DatabaseSchemaQuery {
    return node?.kind === NodeKind.DatabaseSchemaQuery
}

export function isQueryForGroup(query: PersonsNode | ActorsQuery): boolean {
    return (
        isActorsQuery(query) &&
        isInsightActorsQuery(query.source) &&
        isRetentionQuery(query.source.source) &&
        query.source.source.aggregation_group_type_index !== undefined
    )
}

export function isAsyncResponse(response: NonNullable<QuerySchema['response']>): response is QueryStatusResponse {
    return 'query_status' in response && response.query_status
}

export function shouldQueryBeAsync(query: Node): boolean {
    return (
        isInsightQueryNode(query) ||
        isHogQLQuery(query) ||
        (isDataTableNode(query) && isInsightQueryNode(query.source)) ||
        (isDataVisualizationNode(query) && isInsightQueryNode(query.source))
    )
}

export function isInsightQueryWithSeries(
    node?: Node
): node is TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery {
    return isTrendsQuery(node) || isFunnelsQuery(node) || isStickinessQuery(node) || isLifecycleQuery(node)
}

export function isInsightQueryNode(node?: Record<string, any> | null): node is InsightQueryNode {
    return (
        isTrendsQuery(node) ||
        isFunnelsQuery(node) ||
        isRetentionQuery(node) ||
        isPathsQuery(node) ||
        isStickinessQuery(node) ||
        isLifecycleQuery(node)
    )
}

export function dateRangeFor(node?: Node): DateRange | undefined {
    if (isInsightVizNode(node)) {
        return node.source.dateRange
    } else if (isInsightQueryNode(node)) {
        return node.dateRange
    } else if (isActionsNode(node)) {
        return undefined
    } else if (isEventsNode(node)) {
        return undefined
    } else if (isPersonsNode(node)) {
        return undefined
    } else if (isDataTableNode(node)) {
        return undefined
    }

    return undefined
}

export const getInterval = (query: InsightQueryNode): IntervalType | undefined => {
    if (isInsightQueryWithSeries(query)) {
        return query.interval
    }
    return undefined
}

export const getDisplay = (query: InsightQueryNode): ChartDisplayType | undefined => {
    if (isStickinessQuery(query)) {
        return query.stickinessFilter?.display
    } else if (isTrendsQuery(query)) {
        return query.trendsFilter?.display
    }
    return undefined
}

export const getFormula = (query: InsightQueryNode | null): string | undefined => {
    if (isTrendsQuery(query)) {
        return (
            query.trendsFilter?.formulaNodes?.[0]?.formula ||
            query.trendsFilter?.formulas?.[0] ||
            query.trendsFilter?.formula
        )
    }
    return undefined
}

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

export const getSeries = (query: InsightQueryNode): (EventsNode | ActionsNode | DataWarehouseNode)[] | undefined => {
    if (isInsightQueryWithSeries(query)) {
        return query.series
    }
    return undefined
}

export const getBreakdown = (query: InsightQueryNode): BreakdownFilter | undefined => {
    if (isInsightQueryWithBreakdown(query)) {
        return query.breakdownFilter
    }
    return undefined
}

export const getCompareFilter = (query: InsightQueryNode): CompareFilter | undefined => {
    if (isInsightQueryWithCompare(query)) {
        return query.compareFilter
    }
    return undefined
}

export const getShowLegend = (query: InsightQueryNode): boolean | undefined => {
    if (isStickinessQuery(query)) {
        return query.stickinessFilter?.showLegend
    } else if (isTrendsQuery(query)) {
        return query.trendsFilter?.showLegend
    } else if (isLifecycleQuery(query)) {
        return query.lifecycleFilter?.showLegend
    }
    return undefined
}

export const getShowAlertThresholdLines = (query: InsightQueryNode): boolean | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.showAlertThresholdLines
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
    }

    return undefined
}

export const supportsPercentStackView = (q: InsightQueryNode | null | undefined): boolean =>
    isTrendsQuery(q) && PERCENT_STACK_VIEW_DISPLAY_TYPE.includes(getDisplay(q) || ChartDisplayType.ActionsLineGraph)

export const getShowPercentStackView = (query: InsightQueryNode): boolean | undefined =>
    supportsPercentStackView(query) && (query as TrendsQuery)?.trendsFilter?.showPercentStackView

export const nodeKindToFilterProperty: Record<InsightNodeKind, InsightFilterProperty> = {
    [NodeKind.TrendsQuery]: 'trendsFilter',
    [NodeKind.FunnelsQuery]: 'funnelsFilter',
    [NodeKind.RetentionQuery]: 'retentionFilter',
    [NodeKind.PathsQuery]: 'pathsFilter',
    [NodeKind.StickinessQuery]: 'stickinessFilter',
    [NodeKind.LifecycleQuery]: 'lifecycleFilter',
}

export function filterKeyForQuery(node: InsightQueryNode): InsightFilterProperty {
    return nodeKindToFilterProperty[node.kind]
}

export function filterForQuery(node: InsightQueryNode): InsightFilter | undefined {
    const filterProperty = nodeKindToFilterProperty[node.kind]
    return node[filterProperty as keyof InsightQueryNode] as InsightFilter | undefined
}

export function isQuoted(identifier: string): boolean {
    return (
        (identifier.startsWith('"') && identifier.endsWith('"')) ||
        (identifier.startsWith('`') && identifier.endsWith('`'))
    )
}

export function trimQuotes(identifier: string): string {
    if (isQuoted(identifier)) {
        return identifier.slice(1, -1)
    }
    return identifier
}

/** Make sure the property key is wrapped in quotes if it contains any special characters. */
export function escapePropertyAsHogQLIdentifier(identifier: string): string {
    if (identifier.match(/^[A-Za-z_$][A-Za-z0-9_$]*$/)) {
        // Same regex as in the backend escape_hogql_identifier
        return identifier // This identifier is simple
    }
    if (isQuoted(identifier)) {
        return identifier // This identifier is already quoted
    }
    return !identifier.includes('"') ? `"${identifier}"` : `\`${identifier}\``
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

declare const __hogqlBrand: unique symbol
export type HogQLQueryString = string & { readonly [__hogqlBrand]: void }

export interface HogQLIdentifier {
    __hogql_identifier: true
    identifier: string
}

function hogQLIdentifier(identifier: string): HogQLIdentifier {
    return {
        __hogql_identifier: true,
        identifier,
    }
}

function isHogQLIdentifier(value: any): value is HogQLIdentifier {
    return !!value?.__hogql_identifier
}

export interface HogQLRaw {
    __hogql_raw: true
    raw: string
}

function hogQLRaw(raw: string): HogQLRaw {
    return {
        __hogql_raw: true,
        raw,
    }
}

function isHogQLRaw(value: any): value is HogQLRaw {
    return !!value?.__hogql_raw
}

function formatHogQLValue(value: any): string {
    if (Array.isArray(value)) {
        return `[${value.map(formatHogQLValue).join(', ')}]`
    } else if (dayjs.isDayjs(value)) {
        const timezone = getAppContext()?.current_team?.timezone || 'UTC'
        return value.tz(timezone).format("'YYYY-MM-DD HH:mm:ss'")
    } else if (isHogQLIdentifier(value)) {
        return escapePropertyAsHogQLIdentifier(value.identifier)
    } else if (isHogQLRaw(value)) {
        return value.raw
    } else if (typeof value === 'string') {
        return `'${value}'`
    } else if (typeof value === 'number') {
        return String(value)
    } else if (value === null) {
        throw new Error(
            `null cannot be interpolated for SQL. if a null check is needed, make 'IS NULL' part of your query`
        )
    } else {
        throw new Error(`Unsupported interpolated value type: ${typeof value}`)
    }
}

/**
 * Template tag for HogQL formatting. Handles formatting of values for you.
 * @example hogql`SELECT * FROM events WHERE properties.text = ${text} AND timestamp > ${dayjs()}`
 */
export function hogql(strings: TemplateStringsArray, ...values: any[]): HogQLQueryString {
    return strings.reduce(
        (acc, str, i) => acc + str + (i < strings.length - 1 ? formatHogQLValue(values[i]) : ''),
        ''
    ) as unknown as HogQLQueryString
}
hogql.identifier = hogQLIdentifier
hogql.raw = hogQLRaw

/**
 * Wether we have a valid `breakdownFilter` or not.
 */
export function isValidBreakdown(breakdownFilter?: BreakdownFilter | null): breakdownFilter is BreakdownFilter {
    return !!(
        breakdownFilter &&
        ((breakdownFilter.breakdown && breakdownFilter.breakdown_type) ||
            (breakdownFilter.breakdowns && breakdownFilter.breakdowns.length > 0))
    )
}

export function isValidQueryForExperiment(query: Node): boolean {
    return isNodeWithSource(query) && isFunnelsQuery(query.source) && query.source.series.length >= 2
}

export function isGroupsQuery(node?: Record<string, any> | null): node is GroupsQuery {
    return node?.kind === NodeKind.GroupsQuery
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

/**
 * **Needs to be used on all hardcoded queries.**
 *
 * Recursively adds the latest version for the respective kind to each node. This
 * is necessary so that schema migrations don't run on hardcoded queries that
 * are already the latest version. */
export function setLatestVersionsOnQuery<T = any>(node: T, options?: { recursion?: boolean }): T {
    const recursion = options?.recursion ?? true

    if (node === null || typeof node !== 'object') {
        return node
    }

    if (recursion === true && Array.isArray(node)) {
        return (node as unknown as any[]).map((value) => setLatestVersionsOnQuery(value)) as unknown as T
    }

    const cloned: Record<string, any> = { ...(node as any) }

    if (
        'kind' in cloned &&
        Object.values(NodeKind).includes(cloned.kind) &&
        LATEST_VERSIONS[cloned.kind as NodeKind] > 1
    ) {
        const latest = LATEST_VERSIONS[cloned.kind as NodeKind]
        cloned.version = latest || 1
    }

    if (recursion === true) {
        for (const [key, value] of Object.entries(cloned)) {
            if (value !== null && typeof value === 'object') {
                cloned[key] = setLatestVersionsOnQuery(value)
            }
        }
    }

    return cloned as T
}

/** Checks wether a given query node satisfies all latest versions of the query schema. */
export function checkLatestVersionsOnQuery(node: any): boolean {
    if (node === null || typeof node !== 'object') {
        return true
    }

    if (Array.isArray(node)) {
        return node.every((value) => checkLatestVersionsOnQuery(value))
    }

    if ('kind' in node && Object.values(NodeKind).includes(node.kind)) {
        const latest = LATEST_VERSIONS[node.kind as NodeKind]
        if (node.version !== latest) {
            return false
        }
    }

    for (const value of Object.values(node)) {
        if (!checkLatestVersionsOnQuery(value)) {
            return false
        }
    }

    return true
}
