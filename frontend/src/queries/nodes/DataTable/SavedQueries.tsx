import equal from 'fast-deep-equal'
import { useValues } from 'kea'

import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { teamLogic } from 'scenes/teamLogic'

import { getEventsQueriesForTeam } from '~/queries/nodes/DataTable/defaultEventsQuery'
import { DataTableNode } from '~/queries/schema/schema-general'

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
                matchWidth: false,
                overlay: Object.entries(eventsQueries).map(([title, eventsQuery]) => (
                    <LemonButton
                        key={title}
                        fullWidth
                        active={title === selectedTitle}
                        onClick={() => setQuery?.({ ...query, source: eventsQuery })}
                    >
                        {title}
                    </LemonButton>
                )),
            }}
            type="secondary"
        >
            {selectedTitle}
        </LemonButtonWithDropdown>
    )
}
