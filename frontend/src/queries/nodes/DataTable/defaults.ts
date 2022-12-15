import { DataNode, DataTableColumn, DataTableNode } from '~/queries/schema'
import { isEventsNode, isEventsQuery, isPersonsNode } from '~/queries/utils'

export const defaultDataTableEventColumns: DataTableColumn[] = [
    '*',
    'event',
    'person',
    'url',
    'properties.$lib',
    'timestamp',
]

export const defaultDataTablePersonColumns: DataTableColumn[] = ['person', 'id', 'created_at', 'person.$delete']

export function defaultDataTableColumns(query: DataNode): DataTableColumn[] {
    return isPersonsNode(query)
        ? defaultDataTablePersonColumns
        : isEventsQuery(query)
        ? defaultDataTableEventColumns
        : isEventsNode(query)
        ? defaultDataTableEventColumns.filter((c) => c !== '*')
        : []
}

export function defaultColumns(query: DataTableNode): DataTableColumn[] {
    return (
        query.columns ??
        (isEventsQuery(query.source) && Array.isArray(query.source.select) && query.source.select.length > 0
            ? query.source.select
            : null) ??
        defaultDataTableColumns(query.source)
    )
}
