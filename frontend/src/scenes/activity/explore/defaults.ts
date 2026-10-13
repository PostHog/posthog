import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, TeamPublicType, TeamType } from '~/types'

const EVENT_LOOKUP_FILTER = /^uuid = '[a-f0-9-]+'$/

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

// An event link opens the events scene with this query. isUnnamedEventLookup recognizes its filter. Change the two together.
export const getEventLookupQuery = (id: string): DataTableNode =>
    getDefaultEventsSceneQuery([
        { type: PropertyFilterType.HogQL, key: `uuid = '${id.replaceAll(/[^a-f0-9-]/g, '')}'`, value: null },
    ])

export function isUnnamedEventLookup(source: EventsQuery): boolean {
    const [filter, ...otherFilters] = source.properties ?? []
    return (
        !source.event &&
        !source.events?.length &&
        otherFilters.length === 0 &&
        filter?.type === PropertyFilterType.HogQL &&
        EVENT_LOOKUP_FILTER.test(filter.key)
    )
}

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
