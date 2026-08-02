import { getDefaultEventsSceneQuery } from 'scenes/activity/explore/defaults'

import { EventsQuery, NodeKind } from '~/queries/schema/schema-general'
import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'
import { TeamType } from '~/types'

/** Indicates HogQL usage if team.live_events_columns = [HOGQL_COLUMNS_KEY, ...] */
export const HOGQL_COLUMNS_KEY = '--v2:hogql'

export function cleanLiveEventsColumns(columns: string[]): string[] {
    // new columns
    if (columns.length > 0 && columns[0] === HOGQL_COLUMNS_KEY) {
        return columns.slice(1)
    }
    // legacy columns
    return [
        '*',
        ...columns.map((column) => {
            if (column === 'event' || column === 'person') {
                return column
            }
            if (column === 'url') {
                return 'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen'
            }
            if (column === 'source') {
                return 'properties.$lib'
            }
            return `properties.${escapePropertyAsHogQLIdentifier(String(column))}`
        }),
        'timestamp',
    ]
}

export function getDefaultEventsQueryForTeam(team: Partial<TeamType>): EventsQuery | null {
    const liveColumns = team?.live_events_columns ? cleanLiveEventsColumns(team.live_events_columns) : null

    // Always prepend '*' — the column configurator saves `live_events_columns` without it
    // (see ColumnConfigurator.tsx), but the row-expand toggle relies on '*' being present in
    // the response columns.
    const select = liveColumns ? (liveColumns.includes('*') ? liveColumns : ['*', ...liveColumns]) : null

    return select
        ? {
              kind: NodeKind.EventsQuery,
              select,
              after: '-1h',
              orderBy: select.includes('timestamp') ? ['timestamp DESC'] : [],
          }
        : null
}

/**
 * Build the query for a view the user just picked, keeping the parts of their current query that
 * describe how they are looking at events rather than which view they are in: the date range and
 * the test-account toggle. Each preset carries its own `after`, so without this a view switch
 * would silently drag the user back to the preset's window.
 *
 * These are the same fields `SavedQueries` leaves out when working out which view is active, since
 * changing them does not move you off a view.
 */
export function applyEventsViewPreset(preset: EventsQuery, current: EventsQuery): EventsQuery {
    return {
        ...preset,
        ...('filterTestAccounts' in current ? { filterTestAccounts: current.filterTestAccounts } : {}),
        ...('after' in current ? { after: current.after } : {}),
        ...('before' in current ? { before: current.before } : {}),
    }
}

export function getEventsQueriesForTeam(team: Partial<TeamType>): Record<string, EventsQuery> {
    const projectDefault = getDefaultEventsQueryForTeam(team)
    return {
        ...(projectDefault ? { 'Project default view': projectDefault } : {}),
        'PostHog default view': getDefaultEventsSceneQuery().source as EventsQuery,
        'Event counts view': {
            kind: NodeKind.EventsQuery,
            select: ['event', 'count()'],
            after: '-1h',
            orderBy: ['count() DESC'],
        } as EventsQuery,
    }
}
