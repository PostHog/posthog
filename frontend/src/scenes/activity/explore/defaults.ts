import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/schema'
import { AnyPropertyFilter } from '~/types'

export const getDefaultEventsSceneQuery = (properties?: AnyPropertyFilter[]): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: defaultDataTableColumns(NodeKind.EventsQuery),
        orderBy: ['timestamp DESC'],
        after: '-24h',
        ...(properties ? { properties } : {}),
        modifiers: {
            usePresortedEventsTable: true,
        },
    },
    propertiesViaUrl: true,
    showSavedQueries: true,
    showPersistentColumnConfigurator: true,
})
