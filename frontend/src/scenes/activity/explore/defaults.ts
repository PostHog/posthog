import { dayjs } from 'lib/dayjs'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, TeamPublicType, TeamType } from '~/types'

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

/** Hours either side of a known event when deep-linking to the moment it happened. */
const EVENTS_AROUND_TIMESTAMP_HOURS = 1
/** Lookback for a person's events when we know who to look at but not when. */
const PERSON_EVENTS_FALLBACK_AFTER = '-7d'

/**
 * Events scene query for a single distinct ID.
 *
 * The scene's own `-1h` default is meant for live traffic, so it leaves these links empty for anything but a
 * person who is active right now. Pass `aroundTimestamp` (e.g. the timestamp of the survey response or event the
 * link sits on) to center the window on that moment instead; without one we fall back to a wider lookback.
 */
export const getPersonEventsSceneQuery = (
    distinctId: string | undefined,
    aroundTimestamp?: string | null
): DataTableNode => {
    const query = getDefaultEventsSceneQuery([
        {
            type: PropertyFilterType.EventMetadata,
            key: 'distinct_id',
            value: distinctId,
            operator: PropertyOperator.Exact,
        },
    ])
    const source = query.source as EventsQuery
    const anchor = aroundTimestamp ? dayjs(aroundTimestamp) : null

    if (anchor?.isValid()) {
        source.after = anchor.subtract(EVENTS_AROUND_TIMESTAMP_HOURS, 'hour').toISOString()
        source.before = anchor.add(EVENTS_AROUND_TIMESTAMP_HOURS, 'hour').toISOString()
    } else {
        source.after = PERSON_EVENTS_FALLBACK_AFTER
    }

    return query
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
