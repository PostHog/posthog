import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { IconBookmarkBorder } from 'lib/lemon-ui/icons'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema'
import equal from 'fast-deep-equal'
import { getDefaultEventsSceneQuery } from 'scenes/events/defaults'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { HOGQL_COLUMNS_KEY } from '~/queries/nodes/DataTable/ColumnConfigurator/columnConfiguratorLogic'
import { TeamType } from '~/types'

interface SavedQueriesProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
}

function getEventsQueriesForTeam(team: Partial<TeamType>): Record<string, EventsQuery> {
    const defaultEventsQueries = {
        'PostHog default': getDefaultEventsSceneQuery().source as EventsQuery,
        'Event counts': {
            kind: NodeKind.EventsQuery,
            select: ['event', 'count()'],
            after: '-24h',
            orderBy: ['count() DESC'],
        } as EventsQuery,
    }

    const liveColumns = team?.live_events_columns ? migrateLegacyLiveEventsColumns(team.live_events_columns) : null
    return liveColumns
        ? {
              'Project default': {
                  kind: NodeKind.EventsQuery,
                  select: liveColumns,
                  after: '-24h',
                  orderBy: liveColumns.includes('timestamp') ? ['timestamp DESC'] : [],
              },
              ...defaultEventsQueries,
          }
        : defaultEventsQueries
}

function migrateLegacyLiveEventsColumns(columns: string[]): string[] {
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

export function SavedQueries({ query, setQuery }: SavedQueriesProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    if (!setQuery || !currentTeam) {
        return null
    }

    const eventsQueries = getEventsQueriesForTeam(currentTeam)
    let selectedTitle = Object.keys(eventsQueries).find((key) => equal(eventsQueries[key], query.source))

    if (!selectedTitle) {
        // is there any query that only changed the dates
        selectedTitle = Object.keys(eventsQueries).find((key) => {
            return equal({ ...eventsQueries[key], before: '', after: '' }, { ...query.source, before: '', after: '' })
        })
    }
    if (!selectedTitle) {
        selectedTitle = 'Custom query'
    }

    return (
        <LemonButtonWithDropdown
            dropdown={{
                sameWidth: false,
                overlay: Object.entries(eventsQueries).map(([title, eventsQuery]) => (
                    <LemonButton
                        key={title}
                        fullWidth
                        status={title === selectedTitle ? 'primary' : 'stealth'}
                        onClick={() => setQuery?.({ ...query, source: eventsQuery })}
                    >
                        {title}
                    </LemonButton>
                )),
            }}
            type="secondary"
            status="primary-alt"
            icon={<IconBookmarkBorder />}
        >
            {selectedTitle}
        </LemonButtonWithDropdown>
    )
}
