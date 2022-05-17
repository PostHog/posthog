import { DateTime } from 'luxon'

import { Hub, Person, PreIngestionEvent, TeamId } from '../../types'

// context: https://github.com/PostHog/posthog/issues/9182
// TL;DR: events from a recently created non-anonymous person are sent to a buffer
// because their person_id might change. We merge based on the person_id of the anonymous user
// so ingestion is delayed for those events to increase our chances of getting person_id correctly
export function shouldSendEventToBuffer(
    hub: Hub,
    event: PreIngestionEvent,
    person: Person | undefined,
    teamId: TeamId
): boolean {
    const isAnonymousEvent =
        event.properties && event.properties['$device_id'] && event.distinctId === event.properties['$device_id']
    const isRecentPerson = !person || DateTime.now().diff(person.created_at).seconds < hub.BUFFER_CONVERSION_SECONDS
    const ingestEventDirectly = isAnonymousEvent || event.event === '$identify' || !isRecentPerson
    const sendToBuffer = !ingestEventDirectly

    if (sendToBuffer) {
        hub.statsd?.increment('conversion_events_buffer_size', { teamId: event.teamId.toString() })
    }

    if (!hub.CONVERSION_BUFFER_ENABLED && !hub.conversionBufferEnabledTeams.has(teamId)) {
        return false
    }

    return sendToBuffer
}
