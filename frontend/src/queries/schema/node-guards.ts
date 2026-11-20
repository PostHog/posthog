import { BIVisualizationNode } from './schema-business-intelligence'
import {
    ActionsNode,
    ActorsQuery,
    AnyDataWarehouseNode,
    BreakdownFilter,
    DataTableNode,
    DataWarehouseNode,
    EventsNode,
    FunnelsDataWarehouseNode,
    FunnelsQuery,
    GroupNode,
    HogQLQuery,
    InsightQueryNode,
    InsightVizNode,
    LifecycleDataWarehouseNode,
    LifecycleQuery,
    MetricsQuery,
    Node,
    NodeKind,
    PathsQuery,
    PathsV2Query,
    PersonsNode,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
    VisualizationNode,
    WebOverviewQuery,
    WebStatsTableQuery,
} from './schema-general'

export function isNodeWithSource(
    node?: Record<string, any> | null
): node is DataTableNode | VisualizationNode | InsightVizNode {
    if (!node) {
        return false
    }

    return isDataTableNode(node) || isDataVisualizationNode(node) || isInsightVizNode(node)
}

export function isEventsNode(node?: Record<string, any> | null): node is EventsNode {
    return node?.kind === NodeKind.EventsNode
}

export function isGroupNode(node?: Record<string, any> | null): node is GroupNode {
    return node?.kind === NodeKind.GroupNode
}

export function isActionsNode(node?: Record<string, any> | null): node is ActionsNode {
    return node?.kind === NodeKind.ActionsNode
}

export function isDataWarehouseNode(node?: Record<string, any> | null): node is DataWarehouseNode {
    return node?.kind === NodeKind.DataWarehouseNode
}

export function isFunnelsDataWarehouseNode(node?: Record<string, any> | null): node is FunnelsDataWarehouseNode {
    return node?.kind === NodeKind.FunnelsDataWarehouseNode
}

export function isLifecycleDataWarehouseNode(node?: Record<string, any> | null): node is LifecycleDataWarehouseNode {
    return node?.kind === NodeKind.LifecycleDataWarehouseNode
}

export function isAnyDataWarehouseNode(node?: Record<string, any> | null): node is AnyDataWarehouseNode {
    return isDataWarehouseNode(node) || isFunnelsDataWarehouseNode(node) || isLifecycleDataWarehouseNode(node)
}

/** @deprecated `ActorsQuery` is now used instead of `PersonsNode`. */
export function isPersonsNode(node?: Record<string, any> | null): node is PersonsNode {
    return node?.kind === NodeKind.PersonsNode
}

export function isActorsQuery(node?: Record<string, any> | null): node is ActorsQuery {
    return node?.kind === NodeKind.ActorsQuery
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

export function isBIVisualizationNode(node?: Record<string, any> | null): node is BIVisualizationNode {
    return node?.kind === NodeKind.BIVisualizationNode
}

export function isDataVisualizationNode(node?: Record<string, any> | null): node is VisualizationNode {
    return node?.kind === NodeKind.DataVisualizationNode || isBIVisualizationNode(node)
}

export function isDataVisualizationNodeWithHogQLQuery(
    node?: Record<string, any> | null
): node is VisualizationNode & { source: HogQLQuery } {
    return isDataVisualizationNode(node) && isHogQLQuery(node.source)
}

export function isInsightVizNode(node?: Record<string, any> | null): node is InsightVizNode {
    return node?.kind === NodeKind.InsightVizNode
}

export function isHogQLQuery(node?: Record<string, any> | null): node is HogQLQuery {
    return node?.kind === NodeKind.HogQLQuery
}

export function isMetricsQuery(node?: Record<string, any> | null): node is MetricsQuery {
    return node?.kind === NodeKind.MetricsQuery
}

export function isWebOverviewQuery(node?: Record<string, any> | null): node is WebOverviewQuery {
    return node?.kind === NodeKind.WebOverviewQuery
}

export function isWebStatsTableQuery(node?: Record<string, any> | null): node is WebStatsTableQuery {
    return node?.kind === NodeKind.WebStatsTableQuery
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

export function isPathsV2Query(node?: Record<string, any> | null): node is PathsV2Query {
    return node?.kind === NodeKind.PathsV2Query
}

export function isStickinessQuery(node?: Record<string, any> | null): node is StickinessQuery {
    return node?.kind === NodeKind.StickinessQuery
}

export function isLifecycleQuery(node?: Record<string, any> | null): node is LifecycleQuery {
    return node?.kind === NodeKind.LifecycleQuery
}

export function isInsightQueryWithBreakdown(
    node?: Record<string, any> | null
): node is TrendsQuery | FunnelsQuery | RetentionQuery {
    return isTrendsQuery(node) || isFunnelsQuery(node) || isRetentionQuery(node)
}

export function isInsightQueryWithCompare(
    node?: Record<string, any> | null
): node is TrendsQuery | StickinessQuery | WebStatsTableQuery | WebOverviewQuery | FunnelsQuery {
    return (
        isTrendsQuery(node) ||
        isStickinessQuery(node) ||
        isWebStatsTableQuery(node) ||
        isWebOverviewQuery(node) ||
        isFunnelsQuery(node)
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
        isPathsV2Query(node) ||
        isStickinessQuery(node) ||
        isLifecycleQuery(node) ||
        isWebStatsTableQuery(node) ||
        isWebOverviewQuery(node)
    )
}

type SingleBreakdownFilter = BreakdownFilter & {
    breakdown: NonNullable<BreakdownFilter['breakdown']>
}

type MultiBreakdownFilter = BreakdownFilter & {
    breakdowns: NonNullable<BreakdownFilter['breakdowns']>
}

type PopulatedBreakdownFilter = SingleBreakdownFilter | MultiBreakdownFilter

export function hasSingleBreakdown(breakdownFilter?: BreakdownFilter | null): breakdownFilter is SingleBreakdownFilter {
    return breakdownFilter?.breakdown != null
}

export function hasMultiBreakdown(breakdownFilter?: BreakdownFilter | null): breakdownFilter is MultiBreakdownFilter {
    return (breakdownFilter?.breakdowns?.length ?? 0) > 0
}

export function hasBreakdownFilter(
    breakdownFilter?: BreakdownFilter | null
): breakdownFilter is PopulatedBreakdownFilter {
    return hasSingleBreakdown(breakdownFilter) || hasMultiBreakdown(breakdownFilter)
}
