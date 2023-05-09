import { EventsNode, EventsQuery } from '~/queries/schema'
import { LemonEventName } from 'scenes/actions/EventName'

interface EventNameProps {
    query: EventsNode | EventsQuery
    setQuery?: (query: EventsNode | EventsQuery) => void
}

export function EventName({ query, setQuery }: EventNameProps): JSX.Element {
    return (
        <LemonEventName
            value={query.event ?? ''}
            disabled={!setQuery}
            onChange={(value) => setQuery?.({ ...query, event: value })}
            allEventsOption="clear"
        />
    )
}
