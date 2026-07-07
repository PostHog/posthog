import { queryUsesFiltersPlaceholder } from 'scenes/data-warehouse/editor/sql-utils'

import { Node } from '~/queries/schema/schema-general'
import { isDataTableNode, isDataVisualizationNode, isHogQLQuery } from '~/queries/utils'
import { AnyPropertyFilter } from '~/types'

/** Extract the raw SQL string from a HogQL-backed query node, or null if the node isn't HogQL-backed. */
export function getHogQLQueryString(query: Node | null | undefined): string | null {
    if (isHogQLQuery(query)) {
        return query.query
    }
    if ((isDataVisualizationNode(query) || isDataTableNode(query)) && isHogQLQuery(query.source)) {
        return query.source.query
    }
    return null
}

/**
 * Dashboard (or tile) property filters are silently ignored on a SQL insight whose query lacks a
 * `{filters}` placeholder: the backend merges them into the query object but only injects them into
 * the executed SQL when the placeholder is present, so the tile runs unfiltered and shows numbers
 * that look filtered but aren't. Detect that case so we can warn instead of quietly showing wrong data.
 */
export function dashboardFiltersIgnoredOnSqlInsight(
    query: Node | null | undefined,
    propertyFilters: AnyPropertyFilter[] | null | undefined
): boolean {
    if (!propertyFilters?.length) {
        return false
    }
    const hogQLQuery = getHogQLQueryString(query)
    if (hogQLQuery === null) {
        return false
    }
    return !queryUsesFiltersPlaceholder(hogQLQuery)
}
