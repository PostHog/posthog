import { dayjs } from 'lib/dayjs'
import { eventToIcon } from 'scenes/session-recordings/player/inspector/components/PlayerInspectorListItem'
import { urls } from 'scenes/urls'

import { EventDefinition } from '~/types'

import { ProjectHomePageCompactListItem } from '../project-homepage/ProjectHomePageCompactListItem'

export function EventRow({ event }: { event: EventDefinition }): JSX.Element {
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
