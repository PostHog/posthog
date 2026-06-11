import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, TeamPublicType, TeamType } from '~/types'

export const getDefaultEventsSceneQuery = (properties?: AnyPropertyFilter[]): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: defaultDataTableColumns(NodeKind.EventsQuery),
        orderBy: ['timestamp DESC'],
        after: '-1h',
        ...(properties ? { properties } : {}),
    },
    propertiesViaUrl: true,
    showSavedQueries: true,
    showPersistentColumnConfigurator: true,
})

export function applyTestAccountFilter<T extends DataTableNode>(
    base: T,
    currentTeam: TeamType | TeamPublicType | null | undefined,
    filterTestAccountsDefault: boolean
): T {
    const hasTestAccountFilters = (currentTeam?.test_account_filters ?? []).length > 0
    return {
        ...base,
        source: {
            ...base.source,
            ...(hasTestAccountFilters ? { filterTestAccounts: filterTestAccountsDefault } : {}),
        },
    }
}

export const getDefaultSessionsSceneQuery = (properties?: AnyPropertyFilter[]): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.SessionsQuery,
        select: defaultDataTableColumns(NodeKind.SessionsQuery),
        orderBy: ['$end_timestamp DESC NULLS FIRST'],
        after: '-1h',
        limit: 100,
        ...(properties ? { properties } : {}),
    },
    propertiesViaUrl: true,
    showSavedQueries: true,
    showPersistentColumnConfigurator: true,
    contextKey: 'activity-sessions',
})
