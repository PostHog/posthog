import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { DataTableNode } from '~/queries/schema'
import equal from 'fast-deep-equal'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { getEventsQueriesForTeam } from '~/queries/nodes/DataTable/defaultEventsQuery'

interface SavedQueriesProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
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
        >
            {selectedTitle}
        </LemonButtonWithDropdown>
    )
}
