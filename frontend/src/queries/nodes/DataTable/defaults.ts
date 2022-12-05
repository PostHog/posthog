import { DataNode, DataTableStringColumn, NodeKind } from '~/queries/schema'

export const defaultDataTableEventColumns: DataTableStringColumn[] = [
    'event',
    'person',
    'url',
    'properties.$lib',
    'timestamp',
]

export const defaultDataTablePersonColumns: DataTableStringColumn[] = [
    'person',
    'id',
    'created_at',
    'properties.$geoip_country_name',
    'properties.$browser',
]

export function defaultDataTableColumns(query: DataNode): DataTableStringColumn[] {
    return query.kind === NodeKind.PersonsNode ? defaultDataTablePersonColumns : defaultDataTableEventColumns
}
