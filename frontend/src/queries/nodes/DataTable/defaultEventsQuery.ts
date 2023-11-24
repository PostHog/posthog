import { getDefaultEventsSceneQuery } from 'scenes/events/defaults'

import { EventsQuery, NodeKind } from '~/queries/schema'
import { escapePropertyAsHogQlIdentifier } from '~/queries/utils'
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
            return `properties.${escapePropertyAsHogQlIdentifier(String(column))}`
        }),
        'timestamp',
    ]
}

export function getDefaultEventsQueryForTeam(team: Partial<TeamType>): EventsQuery | null {
    const liveColumns = team?.live_events_columns ? cleanLiveEventsColumns(team.live_events_columns) : null
    return liveColumns
        ? {
              kind: NodeKind.EventsQuery,
              select: liveColumns,
              after: '-24h',
              orderBy: liveColumns.includes('timestamp') ? ['timestamp DESC'] : [],
          }
        : null
}

export function getEventsQueriesForTeam(team: Partial<TeamType>): Record<string, EventsQuery> {
    const projectDefault = getDefaultEventsQueryForTeam(team)
    return {
        ...(projectDefault ? { 'Project Default': projectDefault } : {}),
        'PostHog default': getDefaultEventsSceneQuery().source as EventsQuery,
        'Event counts': {
            kind: NodeKind.EventsQuery,
            select: ['event', 'count()'],
            after: '-24h',
            orderBy: ['count() DESC'],
        } as EventsQuery,
    }
}
