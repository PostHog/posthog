import { PERSON_DISPLAY_NAME_COLUMN_NAME } from 'lib/constants'
import { FEATURE_FLAG_CALLED_EVENT, flagCallsListReachesPastRetention } from 'scenes/feature-flags/flagEvaluationsTable'

import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'
import type { TeamPublicType, TeamType } from '~/types'

export const FLAG_CALLS_COLUMNS = [
    '*',
    'properties.$feature_flag',
    'properties.$feature_flag_response',
    PERSON_DISPLAY_NAME_COLUMN_NAME,
    'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen',
    'properties.$lib',
    'timestamp',
]

/** A list of the last 24 hours of flag calls that match `filter`, with no control that can change the event. */
export function flagCallsListQuery(
    filter: Pick<EventsQuery, 'select' | 'personId' | 'fixedProperties'>
): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        full: true,
        // EventsQueryRunner reads flag_evaluations only while the event filter is exactly $feature_flag_called.
        // Another event, an action, a saved table view, or a saved query would send the list back to events.
        showEventFilter: false,
        showEventsFilter: false,
        showTableViews: false,
        showSavedQueries: false,
        showSavedFilters: false,
        source: {
            kind: NodeKind.EventsQuery,
            ...filter,
            event: FEATURE_FLAG_CALLED_EVENT,
            after: '-24h',
        },
    }
}

export function flagCallsTableReachesPastRetention(
    team: TeamPublicType | TeamType | null,
    query: DataTableNode | null
): boolean {
    return !!query && isEventsQuery(query.source) && flagCallsListReachesPastRetention(team, query.source)
}
