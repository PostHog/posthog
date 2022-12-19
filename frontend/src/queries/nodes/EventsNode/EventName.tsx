import { EventsNode, EventsQuery } from '~/queries/schema'
import { LemonEventName } from 'scenes/actions/EventName'

interface EventNameProps {
    query: EventsNode | EventsQuery
    setQuery?: (node: EventsNode | EventsQuery) => void
}

export function EventName({ query, setQuery }: EventNameProps): JSX.Element {
    return (
        <LemonEventName
            value={query.event ?? ''}
            disabled={!setQuery}
            onChange={(value: string) => setQuery?.({ ...query, event: value })}
        />
    )
}
