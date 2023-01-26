import { DataNode, DataTableNode, NodeKind } from '~/queries/schema'
import { isEventsQuery } from '~/queries/utils'

export const defaultDataTableEventColumns: string[] = [
    '*',
    'event',
    'person',
    'coalesce(properties.$current_url, properties.$screen_name) # Url / Screen',
    'properties.$lib',
    'timestamp',
]

export const defaultDataTablePersonColumns: string[] = ['person', 'id', 'created_at', 'person.$delete']

export function defaultDataTableColumns(kind: NodeKind): string[] {
    return kind === NodeKind.PersonsNode
        ? defaultDataTablePersonColumns
        : kind === NodeKind.EventsQuery
        ? defaultDataTableEventColumns
        : kind === NodeKind.EventsNode
        ? defaultDataTableEventColumns.filter((c) => c !== '*')
        : []
}

export function getDataNodeDefaultColumns(source: DataNode): string[] {
    return (
        (isEventsQuery(source) && Array.isArray(source.select) && source.select.length > 0 ? source.select : null) ??
        defaultDataTableColumns(source.kind)
    )
}

export function getColumnsForQuery(query: DataTableNode): string[] {
    return query.columns ?? getDataNodeDefaultColumns(query.source)
}

export function extractExpressionComment(query: string): string {
    if (query.includes('#')) {
        return query.split('#').pop()?.trim() || query
    }
    return query
}

export function removeExpressionComment(query: string): string {
    if (query.includes('#')) {
        return query.split('#').slice(0, -1).join('#').trim()
    }
    return query.trim()
}
