import { EventsNode, EventsQuery, SessionsQuery } from '~/queries/schema/schema-general'

import { EventName as EventNameComponent } from 'products/actions/frontend/components/EventName'

interface EventNameProps {
    query: EventsNode | EventsQuery | SessionsQuery
    setQuery?: (query: EventsNode | EventsQuery | SessionsQuery) => void
}

export function EventName({ query, setQuery }: EventNameProps): JSX.Element {
    return (
        <EventNameComponent
            value={query.event ?? ''}
            disabled={!setQuery}
            onChange={(value) => setQuery?.({ ...query, event: value })}
            allEventsOption="clear"
        />
    )
}
