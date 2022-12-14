import { DataNode, DataTableColumn, DataTableNode, NodeKind } from '~/queries/schema'
import { isEventsNode } from '~/queries/utils'

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

export function defaultsForDataTable(query: DataTableNode, defaultColumns?: DataTableColumn[]): DataTableColumn[] {
    return (
        query.columns ?? (isEventsNode(query.source) ? defaultColumns : null) ?? defaultDataTableColumns(query.source)
    )
}
