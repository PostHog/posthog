import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

export const getDefaultEventsSceneQuery = (properties?: AnyPropertyFilter[]): DataTableNode => {
    const columns = [...defaultDataTableColumns(NodeKind.EventsQuery)]
    // Add inserted_at column for recent events table
    if (!columns.includes('inserted_at')) {
        columns.push('inserted_at')
    }

    return {
        kind: NodeKind.DataTableNode,
        full: true,
        source: {
            kind: NodeKind.EventsQuery,
            select: columns,
            orderBy: ['inserted_at DESC'],
            after: '-24h',
            useRecentEventsTable: true,
            ...(properties ? { properties } : {}),
            modifiers: {
                usePresortedEventsTable: true,
            },
        },
        propertiesViaUrl: true,
        showSavedQueries: true,
        showPersistentColumnConfigurator: true,
    }
}
