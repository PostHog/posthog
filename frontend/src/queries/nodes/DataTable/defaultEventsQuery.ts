import { TeamType } from '~/types'
import { EventsQuery, NodeKind } from '~/queries/schema'
import { getDefaultEventsSceneQuery } from 'scenes/events/defaults'
import { HOGQL_COLUMNS_KEY } from '~/queries/nodes/DataTable/ColumnConfigurator/columnConfiguratorLogic'

export function getDefaultEventsQueryForTeam(team: Partial<TeamType>): EventsQuery | null {
    const liveColumns = team?.live_events_columns ? migrateLegacyLiveEventsColumns(team.live_events_columns) : null
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

export function migrateLegacyLiveEventsColumns(columns: string[]): string[] {
    // new columns
    if (columns.length > 0 && columns[0] === HOGQL_COLUMNS_KEY) {
        return columns.slice(1)
    }
    // legacy columns
    return columns.map((column) => {
        if (column === 'event' || column === 'person') {
            return column
        }
        if (column === 'url') {
            return 'coalesce(properties.$current_url, properties.$screen_name) -- Url / Screen'
        }
        if (column === 'source') {
            return 'properties.$lib'
        }
        return `properties.${column}`
    })
}
