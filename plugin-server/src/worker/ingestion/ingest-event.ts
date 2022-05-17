import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'
import { CachedPersonData } from 'utils/db/db'

import { Element, Hub, IngestEventResponse, Person, PreIngestionEvent, TeamId } from '../../types'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { Action } from './../../types'
import { generateEventDeadLetterQueueMessage } from './utils'

export async function ingestEvent(hub: Hub, event: PluginEvent): Promise<IngestEventResponse> {
    const timeout = timeoutGuard('Still ingesting event inside worker. Timeout warning after 30 sec!', {
        event: JSON.stringify(event),
    })
    try {
        const { ip, site_url, team_id, now, sent_at, uuid } = event
        const distinctId = String(event.distinct_id)
        const preIngestionEvent = await hub.eventsProcessor.processEvent(
            distinctId,
            ip,
            event,
            team_id,
            DateTime.fromISO(now),
            sent_at ? DateTime.fromISO(sent_at) : null,
            uuid!, // it will throw if it's undefined,
            site_url
        )

        let actionMatches: Action[] = []

        if (preIngestionEvent && preIngestionEvent.event !== '$snapshot') {
            const person = await hub.db.fetchPerson(team_id, distinctId)

            // even if the buffer is disabled we want to get metrics on how many events would have gone to it
            const sendEventToBuffer = shouldSendEventToBuffer(hub, preIngestionEvent, person, team_id)

            if (sendEventToBuffer) {
                await hub.eventsProcessor.produceEventToBuffer(preIngestionEvent)
            } else {
                const [, , elements] = await hub.eventsProcessor.createEvent(preIngestionEvent)
                actionMatches = await handleActionMatches(hub, preIngestionEvent, elements, person)
            }
        }

        return { actionMatches, preIngestionEvent, success: true }
    } catch (e) {
        status.info('🔔', e)
        Sentry.captureException(e, { extra: { event } })

        if (hub.db.kafkaProducer) {
            try {
                const message = generateEventDeadLetterQueueMessage(event, e)
                await hub.db.kafkaProducer.queueMessage(message)
                hub.statsd?.increment('events_added_to_dead_letter_queue')
            } catch (dlqError) {
                status.info('🔔', `Errored trying to add event ${event.event} to dead letter queue. Error: ${dlqError}`)
                Sentry.captureException(e, { extra: { event } })
            }
        }
        return { success: false, error: e.message }
    } finally {
        clearTimeout(timeout)
    }
}

export async function ingestBufferEvent(hub: Hub, event: PreIngestionEvent): Promise<IngestEventResponse> {
    const person = await hub.db.getPersonData(event.teamId, event.distinctId)
    const [, , elements] = await hub.eventsProcessor.createEvent(event)
    const actionMatches = await handleActionMatches(hub, event, elements, person ?? undefined)
    return { success: true, actionMatches, preIngestionEvent: event }
}

async function handleActionMatches(
    hub: Hub,
    event: PreIngestionEvent,
    elements?: Element[],
    person?: CachedPersonData | Person
): Promise<Action[]> {
    let actionMatches: Action[] = []

    actionMatches = await hub.actionMatcher.match(event, person, elements)
    await hub.hookCannon.findAndFireHooks(event, person, event.siteUrl, actionMatches)

    return actionMatches
}

// context: https://github.com/PostHog/posthog/issues/9182
// TL;DR: events from a recently created non-anonymous person are sent to a buffer
// because their person_id might change. We merge based on the person_id of the anonymous user
// so ingestion is delayed for those events to increase our chances of getting person_id correctly
function shouldSendEventToBuffer(
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
