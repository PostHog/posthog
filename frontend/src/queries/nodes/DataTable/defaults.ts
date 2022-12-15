import { DataNode, DataTableColumn, DataTableNode, NodeKind } from '~/queries/schema'
import { isEventsQuery } from '~/queries/utils'

export const defaultDataTableEventColumns: DataTableColumn[] = [
    'event',
    'person',
    'url',
    'properties.$lib',
    'timestamp',
]

export const defaultDataTablePersonColumns: DataTableColumn[] = ['person', 'id', 'created_at', 'person.$delete']

export function defaultDataTableColumns(query: DataNode): DataTableColumn[] {
    return query.kind === NodeKind.PersonsNode ? defaultDataTablePersonColumns : defaultDataTableEventColumns
}

export function defaultsForDataTable(query: DataTableNode): DataTableColumn[] {
    let columns =
        query.columns ??
        (isEventsQuery(query.source) && Array.isArray(query.source.select) && query.source.select.length > 0
            ? query.source.select
            : null) ??
        defaultDataTableColumns(query.source)
    if (query.hiddenColumns) {
        columns = columns.filter((column) => !query.hiddenColumns?.includes(column))
    }

    return columns
}
