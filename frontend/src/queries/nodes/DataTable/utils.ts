import { DataNode, DataTableNode, HogQLExpression, NodeKind } from '~/queries/schema'
import { isEventsQuery } from '~/queries/utils'

export const defaultDataTableEventColumns: HogQLExpression[] = [
    '*',
    'event',
    'person',
    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
    'properties.$lib',
    'timestamp',
]

export const defaultDataTablePersonColumns: HogQLExpression[] = ['person', 'id', 'created_at', 'person.$delete']

export function defaultDataTableColumns(kind: NodeKind): HogQLExpression[] {
    return kind === NodeKind.PersonsNode
        ? defaultDataTablePersonColumns
        : kind === NodeKind.EventsQuery
        ? defaultDataTableEventColumns
        : kind === NodeKind.EventsNode
        ? defaultDataTableEventColumns.filter((c) => c !== '*')
        : []
}

export function getDataNodeDefaultColumns(source: DataNode): HogQLExpression[] {
    return (
        (isEventsQuery(source) && Array.isArray(source.select) && source.select.length > 0 ? source.select : null) ??
        defaultDataTableColumns(source.kind)
    )
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
