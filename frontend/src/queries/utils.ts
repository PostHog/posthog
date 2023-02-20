import {
    ActionsNode,
    DataTableNode,
    DateRange,
    EventsNode,
    EventsQuery,
    TrendsQuery,
    FunnelsQuery,
    RetentionQuery,
    PathsQuery,
    StickinessQuery,
    LifecycleQuery,
    InsightFilter,
    InsightFilterProperty,
    InsightQueryNode,
    InsightVizNode,
    LegacyQuery,
    Node,
    NodeKind,
    PersonsNode,
    RecentPerformancePageViewNode,
    TimeToSeeDataNode,
    TimeToSeeDataQuery,
    TimeToSeeDataSessionsQuery,
    InsightNodeKind,
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

export function isInsightQueryWithDisplay(node?: Node): node is TrendsQuery | StickinessQuery {
    return isTrendsQuery(node) || isStickinessQuery(node)
}

export function isInsightQueryWithBreakdown(node?: Node): node is TrendsQuery | FunnelsQuery {
    return isTrendsQuery(node) || isFunnelsQuery(node)
}

export function isInsightQueryWithSeries(
    node?: Node
): node is TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery {
    return isTrendsQuery(node) || isFunnelsQuery(node) || isStickinessQuery(node) || isLifecycleQuery(node)
}

export function isInsightQueryNode(node?: Node): node is InsightQueryNode {
    return (
        isTrendsQuery(node) ||
        isFunnelsQuery(node) ||
        isRetentionQuery(node) ||
        isPathsQuery(node) ||
        isStickinessQuery(node) ||
        isLifecycleQuery(node)
    )
}

export function isTimeToSeeDataSessionsQuery(node?: Node): node is TimeToSeeDataSessionsQuery {
    return node?.kind === NodeKind.TimeToSeeDataSessionsQuery
}

export function isTimeToSeeDataQuery(node?: Node): node is TimeToSeeDataQuery {
    return node?.kind === NodeKind.TimeToSeeDataQuery
}

export function isTimeToSeeDataSessionsNode(node?: Node): node is TimeToSeeDataNode {
    return (
        !!node?.kind &&
        [NodeKind.TimeToSeeDataSessionsWaterfallNode, NodeKind.TimeToSeeDataSessionsJSONNode].includes(node?.kind)
    )
}

export function isRecentPerformancePageViewNode(node?: Node): node is RecentPerformancePageViewNode {
    return node?.kind === NodeKind.RecentPerformancePageViewNode
}

export function dateRangeFor(node?: Node): DateRange | undefined {
    if (isInsightQueryNode(node)) {
        return node.dateRange
    } else if (isTimeToSeeDataQuery(node)) {
        return {
            date_from: node.sessionStart,
            date_to: node.sessionEnd,
        }
    } else if (isRecentPerformancePageViewNode(node)) {
        return undefined // convert from number of days to date range
    } else if (isTimeToSeeDataSessionsQuery(node)) {
        return node.dateRange
    } else if (isLegacyQuery(node)) {
        return {
            date_from: node.filters?.date_from,
            date_to: node.filters?.date_to,
        }
    } else if (isActionsNode(node)) {
        return undefined
    } else if (isEventsNode(node)) {
        return undefined
    } else if (isPersonsNode(node)) {
        return undefined
    } else if (isDataTableNode(node)) {
        return undefined
    } else if (isInsightVizNode(node)) {
        return node.source.dateRange
    }

    return undefined
}

const nodeKindToFilterProperty: Record<InsightNodeKind, InsightFilterProperty> = {
    [NodeKind.TrendsQuery]: 'trendsFilter',
    [NodeKind.FunnelsQuery]: 'funnelsFilter',
    [NodeKind.RetentionQuery]: 'retentionFilter',
    [NodeKind.PathsQuery]: 'pathsFilter',
    [NodeKind.StickinessQuery]: 'stickinessFilter',
    [NodeKind.LifecycleQuery]: 'lifecycleFilter',
}

export function filterPropertyForQuery(node: InsightQueryNode): InsightFilterProperty {
    return nodeKindToFilterProperty[node.kind]
}

export function filterForQuery(node: InsightQueryNode): InsightFilter | undefined {
    const filterProperty = nodeKindToFilterProperty[node.kind]
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
        hogQl.includes('count(') ||
        hogQl.includes('any(') ||
        hogQl.includes('sum(') ||
        hogQl.includes('avg(') ||
        hogQl.includes('min(') ||
        hogQl.includes('max(')
    )
}
