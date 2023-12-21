import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import {
    ActionsNode,
    DatabaseSchemaQuery,
    DataTableNode,
    DataVisualizationNode,
    DateRange,
    EventsNode,
    EventsQuery,
    FunnelsQuery,
    HogQLMetadata,
    HogQLQuery,
    InsightFilter,
    InsightFilterProperty,
    InsightNodeKind,
    InsightPersonsQuery,
    InsightQueryNode,
    InsightVizNode,
    LifecycleQuery,
    Node,
    NodeKind,
    PathsQuery,
    PersonsNode,
    PersonsQuery,
    RetentionQuery,
    SavedInsightNode,
    StickinessQuery,
    TimeToSeeDataJSONNode,
    TimeToSeeDataNode,
    TimeToSeeDataQuery,
    TimeToSeeDataSessionsQuery,
    TimeToSeeDataWaterfallNode,
    TrendsQuery,
    WebOverviewQuery,
    WebStatsTableQuery,
    WebTopClicksQuery,
} from '~/queries/schema'

export function isDataNode(node?: Node | null): node is EventsQuery | PersonsNode | TimeToSeeDataSessionsQuery {
    return (
        isEventsNode(node) ||
        isActionsNode(node) ||
        isPersonsNode(node) ||
        isTimeToSeeDataSessionsQuery(node) ||
        isEventsQuery(node) ||
        isPersonsQuery(node) ||
        isHogQLQuery(node) ||
        isHogQLMetadata(node)
    )
}

function isTimeToSeeDataJSONNode(node?: Node | null): node is TimeToSeeDataJSONNode {
    return node?.kind === NodeKind.TimeToSeeDataSessionsJSONNode
}

function isTimeToSeeDataWaterfallNode(node?: Node | null): node is TimeToSeeDataWaterfallNode {
    return node?.kind === NodeKind.TimeToSeeDataSessionsWaterfallNode
}

export function isNodeWithSource(
    node?: Node | null
): node is DataTableNode | InsightVizNode | TimeToSeeDataWaterfallNode | TimeToSeeDataJSONNode {
    if (!node) {
        return false
    }

    return (
        isDataTableNode(node) ||
        isDataVisualizationNode(node) ||
        isInsightVizNode(node) ||
        isTimeToSeeDataWaterfallNode(node) ||
        isTimeToSeeDataJSONNode(node)
    )
}

export function isEventsNode(node?: Node | null): node is EventsNode {
    return node?.kind === NodeKind.EventsNode
}

export function isEventsQuery(node?: Node | null): node is EventsQuery {
    return node?.kind === NodeKind.EventsQuery
}

export function isActionsNode(node?: Node | null): node is ActionsNode {
    return node?.kind === NodeKind.ActionsNode
}

export function isPersonsNode(node?: Node | null): node is PersonsNode {
    return node?.kind === NodeKind.PersonsNode
}

export function isPersonsQuery(node?: Node | null): node is PersonsQuery {
    return node?.kind === NodeKind.PersonsQuery
}

export function isInsightPersonsQuery(node?: Node | null): node is InsightPersonsQuery {
    return node?.kind === NodeKind.InsightPersonsQuery
}

export function isDataTableNode(node?: Node | null): node is DataTableNode {
    return node?.kind === NodeKind.DataTableNode
}

export function isDataVisualizationNode(node?: Node | null): node is DataVisualizationNode {
    return node?.kind === NodeKind.DataVisualizationNode
}

export function isSavedInsightNode(node?: Node | null): node is SavedInsightNode {
    return node?.kind === NodeKind.SavedInsightNode
}

export function isInsightVizNode(node?: Node | null): node is InsightVizNode {
    return node?.kind === NodeKind.InsightVizNode
}

export function isHogQLQuery(node?: Node | null): node is HogQLQuery {
    return node?.kind === NodeKind.HogQLQuery
}

export function isHogQLMetadata(node?: Node | null): node is HogQLMetadata {
    return node?.kind === NodeKind.HogQLMetadata
}

export function isWebOverviewQuery(node?: Node | null): node is WebOverviewQuery {
    return node?.kind === NodeKind.WebOverviewQuery
}

export function isWebStatsTableQuery(node?: Node | null): node is WebStatsTableQuery {
    return node?.kind === NodeKind.WebStatsTableQuery
}

export function isWebTopClicksQuery(node?: Node | null): node is WebTopClicksQuery {
    return node?.kind === NodeKind.WebTopClicksQuery
}

export function containsHogQLQuery(node?: Node | null): boolean {
    if (!node) {
        return false
    }
    return isHogQLQuery(node) || (isNodeWithSource(node) && isHogQLQuery(node.source))
}

/*
 * Insight Queries
 */

export function isTrendsQuery(node?: Node | null): node is TrendsQuery {
    return node?.kind === NodeKind.TrendsQuery
}

export function isFunnelsQuery(node?: Node | null): node is FunnelsQuery {
    return node?.kind === NodeKind.FunnelsQuery
}

export function isRetentionQuery(node?: Node | null): node is RetentionQuery {
    return node?.kind === NodeKind.RetentionQuery
}

export function isPathsQuery(node?: Node | null): node is PathsQuery {
    return node?.kind === NodeKind.PathsQuery
}

export function isStickinessQuery(node?: Node | null): node is StickinessQuery {
    return node?.kind === NodeKind.StickinessQuery
}

export function isLifecycleQuery(node?: Node | null): node is LifecycleQuery {
    return node?.kind === NodeKind.LifecycleQuery
}

export function isInsightQueryWithDisplay(node?: Node | null): node is TrendsQuery | StickinessQuery {
    return isTrendsQuery(node) || isStickinessQuery(node)
}

export function isInsightQueryWithBreakdown(node?: Node | null): node is TrendsQuery | FunnelsQuery {
    return isTrendsQuery(node) || isFunnelsQuery(node)
}

export function isDatabaseSchemaQuery(node?: Node): node is DatabaseSchemaQuery {
    return node?.kind === NodeKind.DatabaseSchemaQuery
}

export function isQueryForGroup(query: PersonsNode | PersonsQuery): boolean {
    return (
        isPersonsQuery(query) &&
        isInsightPersonsQuery(query.source) &&
        isRetentionQuery(query.source.source) &&
        query.source.source.aggregation_group_type_index !== undefined
    )
}

export function isInsightQueryWithSeries(
    node?: Node
): node is TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery {
    return isTrendsQuery(node) || isFunnelsQuery(node) || isStickinessQuery(node) || isLifecycleQuery(node)
}

export function isInsightQueryNode(node?: Node | null): node is InsightQueryNode {
    return (
        isTrendsQuery(node) ||
        isFunnelsQuery(node) ||
        isRetentionQuery(node) ||
        isPathsQuery(node) ||
        isStickinessQuery(node) ||
        isLifecycleQuery(node)
    )
}

export function isTimeToSeeDataSessionsQuery(node?: Node | null): node is TimeToSeeDataSessionsQuery {
    return node?.kind === NodeKind.TimeToSeeDataSessionsQuery
}

export function isTimeToSeeDataQuery(node?: Node | null): node is TimeToSeeDataQuery {
    return node?.kind === NodeKind.TimeToSeeDataQuery
}

export function isTimeToSeeDataSessionsNode(node?: Node | null): node is TimeToSeeDataNode {
    return (
        !!node?.kind &&
        [NodeKind.TimeToSeeDataSessionsWaterfallNode, NodeKind.TimeToSeeDataSessionsJSONNode].includes(node?.kind)
    )
}

export function dateRangeFor(node?: Node): DateRange | undefined {
    if (isInsightQueryNode(node)) {
        return node.dateRange
    } else if (isTimeToSeeDataQuery(node)) {
        return {
            date_from: node.sessionStart,
            date_to: node.sessionEnd,
        }
    } else if (isTimeToSeeDataSessionsQuery(node)) {
        return node.dateRange
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
