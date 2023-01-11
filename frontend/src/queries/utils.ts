import {
    ActionsNode,
    DataTableNode,
    EventsNode,
    EventsQuery,
    FunnelsQuery,
    InsightQueryNode,
    InsightVizNode,
    LegacyQuery,
    LifecycleQuery,
    Node,
    NodeKind,
    PathsQuery,
    PersonsNode,
    RetentionQuery,
    StickinessQuery,
    TimeToSeeDataQuery,
    TimeToSeeDataNode,
    TimeToSeeDataSessionsQuery,
    TrendsQuery,
    UnimplementedQuery,
    RecentPerformancePageViewNode,
} from '~/queries/schema'

export function isDataNode(node?: Node): node is EventsQuery | PersonsNode | TimeToSeeDataSessionsQuery {
    return isEventsQuery(node) || isPersonsNode(node) || isTimeToSeeDataSessionsQuery(node)
}

export function isEventsNode(node?: Node): node is EventsNode {
    return node?.kind === NodeKind.EventsNode
}

export function isEventsQuery(node?: Node): node is EventsQuery {
    return node?.kind === NodeKind.EventsQuery
}

export function isActionsNode(node?: Node): node is ActionsNode {
    return node?.kind === NodeKind.ActionsNode
}

export function isPersonsNode(node?: Node): node is PersonsNode {
    return node?.kind === NodeKind.PersonsNode
}

export function isDataTableNode(node?: Node): node is DataTableNode {
    return node?.kind === NodeKind.DataTableNode
}

export function isInsightVizNode(node?: Node): node is InsightVizNode {
    return node?.kind === NodeKind.InsightVizNode
}

export function isLegacyQuery(node?: Node): node is LegacyQuery {
    return node?.kind === NodeKind.LegacyQuery
}

/*
 * Insight Queries
 */

export function isTrendsQuery(node?: Node): node is TrendsQuery {
    return node?.kind === NodeKind.TrendsQuery
}

export function isFunnelsQuery(node?: Node): node is FunnelsQuery {
    return node?.kind === NodeKind.FunnelsQuery
}

export function isRetentionQuery(node?: Node): node is RetentionQuery {
    return node?.kind === NodeKind.RetentionQuery
}

export function isPathsQuery(node?: Node): node is PathsQuery {
    return node?.kind === NodeKind.PathsQuery
}

export function isStickinessQuery(node?: Node): node is StickinessQuery {
    return node?.kind === NodeKind.StickinessQuery
}

export function isLifecycleQuery(node?: Node): node is LifecycleQuery {
    return node?.kind === NodeKind.LifecycleQuery
}

export function isTimeToSeeDataSessionsNode(node?: Node): node is TimeToSeeDataNode {
    return (
        !!node?.kind &&
        [NodeKind.TimeToSeeDataSessionsWaterfallNode, NodeKind.TimeToSeeDataSessionsJSONNode].includes(node?.kind)
    )
}

export function isTimeToSeeDataSessionsQuery(node?: Node): node is TimeToSeeDataSessionsQuery {
    return node?.kind === NodeKind.TimeToSeeDataSessionsQuery
}

export function isTimeToSeeDataQuery(node?: Node): node is TimeToSeeDataQuery {
    return node?.kind === NodeKind.TimeToSeeDataQuery
}

export function isRecentPerformancePageViewNode(node?: Node): node is RecentPerformancePageViewNode {
    return node?.kind === NodeKind.RecentPerformancePageViewNode
}

export function isUnimplementedQuery(node?: Node): node is UnimplementedQuery {
    return node?.kind === NodeKind.UnimplementedQuery
}

export function isInsightQueryNode(node?: Node): node is InsightQueryNode {
    return (
        isTrendsQuery(node) ||
        isFunnelsQuery(node) ||
        isRetentionQuery(node) ||
        isPathsQuery(node) ||
        isStickinessQuery(node) ||
        isLifecycleQuery(node) ||
        isUnimplementedQuery(node)
    )
}
