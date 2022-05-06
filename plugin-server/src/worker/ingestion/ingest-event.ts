import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'
import { CachedPersonData } from 'utils/db/db'

import { Element, Hub, IngestEventResponse, Person, PreIngestionEvent } from '../../types'
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
        const result = await hub.eventsProcessor.processEvent(
            distinctId,
            ip,
            event,
            team_id,
            DateTime.fromISO(now),
            sent_at ? DateTime.fromISO(sent_at) : null,
            uuid! // it will throw if it's undefined
        )

        let actionMatches: Action[] = []

        if (result) {
            const person = await hub.db.fetchPerson(team_id, distinctId)

            // even if the buffer is disabled we want to get metrics on how many events would have gone to it
            const sendEventToBuffer =
                shouldSendEventToBuffer(hub, result, person) &&
                (hub.CONVERSION_BUFFER_ENABLED || hub.conversionBufferEnabledTeams.has(team_id))

            if (sendEventToBuffer) {
                await hub.eventsProcessor.produceEventToBuffer(result)
            } else {
                const [, eventId, elements] = await hub.eventsProcessor.createEvent(result)
                actionMatches = await handleActionMatches(hub, event, site_url, eventId, elements, person)
            }
        }

        // We don't want to return the inserted DB entry that `processEvent` returns.
        // This response is passed to piscina and would be discarded anyway.
        return { actionMatches, success: true }
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
        return { error: e.message }
    } finally {
        clearTimeout(timeout)
    }
}

export async function ingestBufferEvent(hub: Hub, event: PreIngestionEvent): Promise<IngestEventResponse> {
    const person = await hub.db.getPersonData(event.teamId, event.distinctId)
    const [, eventId, elements] = await hub.eventsProcessor.createEvent(event)
    const actionMatches = await handleActionMatches(hub, event as any, '', eventId, elements, person ?? undefined)
    return { actionMatches, success: true }
}

async function handleActionMatches(
    hub: Hub,
    event: PluginEvent,
    siteUrl: string,
    eventId?: number,
    elements?: Element[],
    person?: CachedPersonData | Person
): Promise<Action[]> {
    let actionMatches: Action[] = []

    actionMatches = await hub.actionMatcher.match(event, person, elements)
    await hub.hookCannon.findAndFireHooks(event, person, siteUrl, actionMatches)

    if (actionMatches.length && eventId !== undefined) {
        await hub.db.registerActionMatch(eventId, actionMatches)
    }

    return actionMatches
}

// context: https://github.com/PostHog/posthog/issues/9182
// TL;DR: events from a recently created non-anonymous person are sent to a buffer
// because their person_id might change. We merge based on the person_id of the anonymous user
// so ingestion is delayed for those events to increase our chances of getting person_id correctly
function shouldSendEventToBuffer(hub: Hub, event: PreIngestionEvent, person?: Person) {
    const isAnonymousEvent =
        event.properties && event.properties['$device_id'] && event.distinctId === event.properties['$device_id']
    const isRecentPerson = !person || DateTime.now().diff(person.created_at).seconds < hub.BUFFER_CONVERSION_SECONDS
    const ingestEventDirectly = isAnonymousEvent || event.event === '$identify' || !isRecentPerson
    const sendToBuffer = !ingestEventDirectly

    if (sendToBuffer) {
        hub.statsd?.increment('conversion_events_buffer_size', { teamId: event.teamId.toString() })
    }

    return sendToBuffer
}
