import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { PERCENT_STACK_VIEW_DISPLAY_TYPE } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import {
    ActionsNode,
    ActorsQuery,
    BreakdownFilter,
    CompareFilter,
    DatabaseSchemaQuery,
    DataTableNode,
    DataVisualizationNode,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    EventsQuery,
    FunnelsQuery,
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
    Node,
    NodeKind,
    PathsQuery,
    PersonsNode,
    RetentionQuery,
    SavedInsightNode,
    SessionAttributionExplorerQuery,
    StickinessQuery,
    TrendsQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebTopClicksQuery,
} from '~/queries/schema'
import { ChartDisplayType, IntervalType } from '~/types'

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

export function isHogQLMetadata(node?: Record<string, any> | null): node is HogQLMetadata {
    return node?.kind === NodeKind.HogQLMetadata
}

export function isWebOverviewQuery(node?: Record<string, any> | null): node is WebOverviewQuery {
    return node?.kind === NodeKind.WebOverviewQuery
}

export function isWebStatsTableQuery(node?: Record<string, any> | null): node is WebStatsTableQuery {
    return node?.kind === NodeKind.WebStatsTableQuery
}

export function isWebTopClicksQuery(node?: Record<string, any> | null): node is WebTopClicksQuery {
    return node?.kind === NodeKind.WebTopClicksQuery
}

export function isSessionAttributionExplorerQuery(
    node?: Record<string, any> | null
): node is SessionAttributionExplorerQuery {
    return node?.kind === NodeKind.SessionAttributionExplorerQuery
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
    return isTrendsQuery(node) || isFunnelsQuery(node)
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

export const getFormula = (query: InsightQueryNode): string | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.formula
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
    }
    return undefined
}

export const getYAxisScaleType = (query: InsightQueryNode): string | undefined => {
    if (isTrendsQuery(query)) {
        return query.trendsFilter?.yAxisScaleType
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
    return node[filterProperty]
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
export function escapePropertyAsHogQlIdentifier(identifier: string): string {
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
        return `properties.${escapePropertyAsHogQlIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.PersonProperties) {
        return `person.properties.${escapePropertyAsHogQlIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.EventFeatureFlags) {
        return `properties.${escapePropertyAsHogQlIdentifier(String(value))}`
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
        return `properties.${escapePropertyAsHogQlIdentifier(String(value))}`
    }
    if (groupType === TaxonomicFilterGroupType.HogQLExpression && value) {
        return String(value)
    }
    return null
}

export function isHogQlAggregation(hogQl: string): boolean {
    return (
        hogQl.includes('count(') ||
        hogQl.includes('any(') ||
        hogQl.includes('sum(') ||
        hogQl.includes('avg(') ||
        hogQl.includes('min(') ||
        hogQl.includes('max(')
    )
}

export interface HogQLIdentifier {
    __hogql_identifier: true
    identifier: string
}

function hogQlIdentifier(identifier: string): HogQLIdentifier {
    return {
        __hogql_identifier: true,
        identifier,
    }
}

function isHogQlIdentifier(value: any): value is HogQLIdentifier {
    return !!value?.__hogql_identifier
}

function formatHogQlValue(value: any): string {
    if (Array.isArray(value)) {
        return `[${value.map(formatHogQlValue).join(', ')}]`
    } else if (dayjs.isDayjs(value)) {
        return value.tz(teamLogic.values.timezone).format("'YYYY-MM-DD HH:mm:ss'")
    } else if (isHogQlIdentifier(value)) {
        return escapePropertyAsHogQlIdentifier(value.identifier)
    } else if (typeof value === 'string') {
        return `'${value}'`
    } else if (typeof value === 'number') {
        return String(value)
    } else if (value === null) {
        throw new Error(
            `null cannot be interpolated for HogQL. if a null check is needed, make 'IS NULL' part of your query`
        )
    } else {
        throw new Error(`Unsupported interpolated value type: ${typeof value}`)
    }
}

/**
 * Template tag for HogQL formatting. Handles formatting of values for you.
 * @example hogql`SELECT * FROM events WHERE properties.text = ${text} AND timestamp > ${dayjs()}`
 */
export function hogql(strings: TemplateStringsArray, ...values: any[]): string {
    return strings.reduce((acc, str, i) => acc + str + (i < strings.length - 1 ? formatHogQlValue(values[i]) : ''), '')
}
hogql.identifier = hogQlIdentifier

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
