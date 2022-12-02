import { DataTableStringColumn } from '~/queries/schema'

export const defaultDataTableStringColumns: DataTableStringColumn[] = [
    'event',
    'person',
    'properties.$current_url',
    'person.properties.email',
    'timestamp',
]
