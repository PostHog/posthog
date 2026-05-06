import { urls } from 'scenes/urls'

import { TimelineMenuItem } from '..'

export function buildOpenInActivityTabMenuItem({
    eventId,
    timestamp,
}: {
    eventId?: string
    timestamp?: string
}): TimelineMenuItem[] {
    if (!eventId || !timestamp) {
        return []
    }

    const activityUrl = urls.currentProject(urls.event(eventId, timestamp))

    return [
        {
            key: 'open-in-activity-tab',
            label: 'Open in activity tab',
            onClick: () => window.open(activityUrl, '_blank', 'noopener,noreferrer'),
        },
    ]
}
