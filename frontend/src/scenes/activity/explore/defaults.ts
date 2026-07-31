import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, TeamPublicType, TeamType } from '~/types'

export type EventsSceneDateRange = { after?: string; before?: string }

/** Fallback for links already narrowed to a single person, where the last hour is nearly always empty. */
export const PERSON_EVENTS_LINK_DATE_RANGE: EventsSceneDateRange = { after: '-7d' }

export const getDefaultEventsSceneQuery = (
    properties?: AnyPropertyFilter[],
    dateRange?: EventsSceneDateRange
): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: defaultDataTableColumns(NodeKind.EventsQuery),
        orderBy: ['timestamp DESC'],
        after: dateRange?.after ?? '-1h',
        ...(dateRange?.before ? { before: dateRange.before } : {}),
        ...(properties ? { properties } : {}),
    },
    propertiesViaUrl: true,
    showSavedQueries: true,
    showPersistentColumnConfigurator: true,
})

/**
 * The events scene keeps its query in the `q` hash param, so a link built while the user is on that
 * scene can carry their current range over instead of resetting the investigation.
 */
export function getPersonEventsLinkDateRange(hashParams: Record<string, any>): EventsSceneDateRange {
    const source = hashParams?.q?.source
    if (source?.kind === NodeKind.EventsQuery && (source.after || source.before)) {
        return {
            after: typeof source.after === 'string' ? source.after : undefined,
            before: typeof source.before === 'string' ? source.before : undefined,
        }
    }
    return PERSON_EVENTS_LINK_DATE_RANGE
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
