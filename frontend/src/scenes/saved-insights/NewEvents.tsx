import { useValues } from 'kea'

import { CompactList } from 'lib/components/CompactList/CompactList'
import { dayjs } from 'lib/dayjs'
import { eventToIcon } from 'scenes/session-recordings/player/inspector/components/PlayerInspectorListItem'
import { urls } from 'scenes/urls'

import { EventDefinition } from '~/types'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'
import { newEventsLogic } from './newEventsLogic'

function EventRow({ event }: { event: EventDefinition }): JSX.Element {
    const subtitle = event.created_at
        ? `Created ${dayjs(event.created_at).fromNow()}`
        : event.last_seen_at
          ? `Last seen ${dayjs(event.last_seen_at).fromNow()}`
          : 'Recently added'

    const EventIcon = eventToIcon(event.name)

    return (
        <ProjectHomePageCompactListItem
            to={urls.eventDefinition(event.id)}
            title={event.name}
            subtitle={subtitle}
            prefix={<EventIcon className="text-lg" />}
            dataAttr="new-event-item"
        />
    )
}

export function NewEvents(): JSX.Element {
    const { newEvents, newEventsLoading } = useValues(newEventsLogic)

    return (
        <CompactList
            title="New events"
            viewAllURL={urls.eventDefinitions()}
            loading={newEventsLoading}
            emptyMessage={{
                title: 'No events found',
                description: 'Finish implementing event tracking to see your events.',
                buttonText: 'View all events',
                buttonTo: urls.eventDefinitions(),
            }}
            items={newEvents.slice(0, 5)}
            renderRow={(event: EventDefinition) => <EventRow key={event.id} event={event} />}
            contentHeightBehavior="fit-content"
        />
    )
}
