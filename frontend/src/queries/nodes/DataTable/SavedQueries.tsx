import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconBookmarkBorder } from 'lib/components/icons'
import { DataTableNode, EventsQuery, NodeKind } from '~/queries/schema'
import { isEventsQuery } from '~/queries/utils'
import equal from 'fast-deep-equal'
import { getDefaultEventsSceneQuery } from 'scenes/events/eventsSceneLogic'

interface SavedQueriesProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
}

const eventsQueries: Record<string, EventsQuery> = {
    'Live events (default)': getDefaultEventsSceneQuery().source as EventsQuery,
    'Event counts': {
        kind: NodeKind.EventsQuery,
        select: ['event', 'count()'],
        after: '-24h',
        orderBy: ['-count()'],
    },
}

export function SavedQueries({ query, setQuery }: SavedQueriesProps): JSX.Element | null {
    if (!setQuery || !isEventsQuery(query.source)) {
        return null
    }

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
        <LemonButtonWithPopup
            popup={{
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
        </LemonButtonWithPopup>
    )
}
