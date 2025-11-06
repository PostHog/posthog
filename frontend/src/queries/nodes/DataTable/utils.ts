import { PERSON_DISPLAY_NAME_COLUMN_NAME } from 'lib/constants'

import { QueryFeature, getQueryFeatures } from '~/queries/nodes/DataTable/queryFeatures'
import { DataNode, DataTableNode, EventsQuery, HogQLExpression, NodeKind } from '~/queries/schema/schema-general'

export const defaultDataTableEventColumns: HogQLExpression[] = [
    '*',
    'event',
    'verified',
    PERSON_DISPLAY_NAME_COLUMN_NAME,
    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
    'properties.$lib',
    'timestamp',
]

export const defaultDataTablePersonColumns: HogQLExpression[] = [PERSON_DISPLAY_NAME_COLUMN_NAME, 'id', 'created_at']

export const defaultDataTableGroupColumns: HogQLExpression[] = ['group_name', 'key', 'created_at']

export function defaultDataTableColumns(kind: NodeKind): HogQLExpression[] {
    return kind === NodeKind.PersonsNode || kind === NodeKind.ActorsQuery
        ? defaultDataTablePersonColumns
        : kind === NodeKind.EventsQuery
          ? defaultDataTableEventColumns
          : kind === NodeKind.EventsNode
            ? defaultDataTableEventColumns.filter((c) => c !== '*')
            : kind === NodeKind.GroupsQuery
              ? defaultDataTableGroupColumns
              : []
}

export function getDataNodeDefaultColumns(source: DataNode): HogQLExpression[] {
    if (
        getQueryFeatures(source).has(QueryFeature.selectAndOrderByColumns) &&
        Array.isArray((source as EventsQuery).select) &&
        (source as EventsQuery).select.length > 0
    ) {
        return (source as EventsQuery).select
    }
    return defaultDataTableColumns(source.kind)
}

export function getColumnsForQuery(query: DataTableNode): HogQLExpression[] {
    return query.columns ?? getDataNodeDefaultColumns(query.source)
}

export function extractExpressionComment(query: string): string {
    if (query.includes('--')) {
        return query.split('--').pop()?.trim() || query
    }
    return query
}

export function removeExpressionComment(query: string): string {
    if (query.includes('--')) {
        return query.split('--').slice(0, -1).join('--').trim()
    }
    return query.trim()
}
