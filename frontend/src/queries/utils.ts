import {
    ActionsNode,
    DataTableNode,
    EventsNode,
    EventsQuery,
    FunnelsQuery,
    InsightFilter,
    InsightFilterProperty,
    InsightQueryNode,
    InsightVizNode,
    LegacyQuery,
    LifecycleQuery,
    Node,
    NodeKind,
    PathsQuery,
    PersonsNode,
    RecentPerformancePageViewNode,
    RetentionQuery,
    StickinessQuery,
    SupportedNodeKind,
    TimeToSeeDataQuery,
    TimeToSeeDataSessionsQuery,
    TrendsQuery,
    UnimplementedQuery,
} from '~/queries/schema'
import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

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

export function isInsightQueryWithDisplay(node?: Node): boolean {
    return isTrendsQuery(node) || isStickinessQuery(node)
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

export function isTimeToSeeDataSessionsQuery(node?: Node): node is TimeToSeeDataSessionsQuery {
    return node?.kind === NodeKind.TimeToSeeDataSessionsQuery
}

export function isTimeToSeeDataQuery(node?: Node): node is TimeToSeeDataQuery {
    return node?.kind === NodeKind.TimeToSeeDataQuery
}

export function isRecentPerformancePageViewNode(node?: Node): node is RecentPerformancePageViewNode {
    return node?.kind === NodeKind.RecentPerformancePageViewNode
}

const nodeKindToFilterProperty: Record<SupportedNodeKind, InsightFilterProperty> = {
    [NodeKind.TrendsQuery]: 'trendsFilter',
    [NodeKind.FunnelsQuery]: 'funnelsFilter',
    [NodeKind.RetentionQuery]: 'retentionFilter',
    [NodeKind.PathsQuery]: 'pathsFilter',
    [NodeKind.StickinessQuery]: 'stickinessFilter',
    [NodeKind.LifecycleQuery]: 'lifecycleFilter',
}

export function filterPropertyForQuery(node: Exclude<InsightQueryNode, UnimplementedQuery>): InsightFilterProperty {
    return nodeKindToFilterProperty[node.kind]
}

export function filterForQuery(node: InsightQueryNode): InsightFilter | undefined {
    if (node.kind === NodeKind.UnimplementedQuery) {
        return undefined
    }
    const filterProperty = filterPropertyForQuery(node)
    return node[filterProperty]
}

export function taxonomicFilterToHogQl(
    groupType: TaxonomicFilterGroupType,
    value: TaxonomicFilterValue
): string | null {
    if (groupType === TaxonomicFilterGroupType.EventProperties) {
        return `properties.${value}`
    }
    if (groupType === TaxonomicFilterGroupType.PersonProperties) {
        return `person.properties.${value}`
    }
    if (groupType === TaxonomicFilterGroupType.EventFeatureFlags) {
        return `properties.${value}`
    }
    if (groupType === TaxonomicFilterGroupType.HogQLExpression && value) {
        return String(value)
    }
    return null
}

export function hogQlToTaxonomicFilter(hogQl: string): [TaxonomicFilterGroupType, TaxonomicFilterValue] {
    if (hogQl.startsWith('person.properties.')) {
        return [TaxonomicFilterGroupType.PersonProperties, hogQl.substring(18)]
    }
    if (hogQl.startsWith('properties.$feature/')) {
        return [TaxonomicFilterGroupType.EventFeatureFlags, hogQl.substring(11)]
    }
    if (hogQl.startsWith('properties.')) {
        return [TaxonomicFilterGroupType.EventProperties, hogQl.substring(11)]
    }
    return [TaxonomicFilterGroupType.HogQLExpression, hogQl]
}

export function isHogQlAggregation(hogQl: string): boolean {
    return (
        hogQl.includes('total(') ||
        hogQl.includes('any(') ||
        hogQl.includes('sum(') ||
        hogQl.includes('avg(') ||
        hogQl.includes('min(') ||
        hogQl.includes('max(')
    )
}
