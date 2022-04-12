import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import { Element,Hub, IngestEventResponse, Person, PreIngestionEvent } from '../../types'
import { timeoutGuard } from '../../utils/db/utils'
import { status } from '../../utils/status'
import { Action } from './../../types'
import { generateEventDeadLetterQueueMessage } from './utils'

const BUFFER_CONVERSION_SECONDS = 60

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
            const sendEventToBuffer = shouldSendEventToBuffer(result, person)
            if (sendEventToBuffer) {
                // will produce to the buffer topic
            }
            // this will become an else
            const [, eventId, elements] = await hub.eventsProcessor.createEvent(result)
            actionMatches = await handleActionMatches(hub, event, site_url, eventId, elements, person)
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
    const person = await hub.db.fetchPerson(event.teamId, event.distinctId)
    const [, eventId, elements] = await hub.eventsProcessor.createEvent(event)
    const actionMatches = await handleActionMatches(hub, event as any, '', eventId, elements, person)
    return { actionMatches, success: true }
}

async function handleActionMatches(
    hub: Hub,
    event: PluginEvent,
    siteUrl: string,
    eventId?: number,
    elements?: Element[],
    person?: Person
): Promise<Action[]> {
    let actionMatches: Action[] = []

    actionMatches = await hub.actionMatcher.match(event, person, elements)
    await hub.hookCannon.findAndFireHooks(event, person, siteUrl, actionMatches)

    // eventId is undefined for CH deployments
    // CH deployments calculate actions on the fly
    if (actionMatches.length && eventId !== undefined) {
        await hub.db.registerActionMatch(eventId, actionMatches)
    }

    return actionMatches
}

function shouldSendEventToBuffer(event: PreIngestionEvent, person?: Person) {
    const isAnonymousEvent =
        event.properties && event.properties['$device_id'] && event.distinctId === event.properties['$device_id']
    const isRecentPerson = !person || DateTime.now().diff(person.created_at).seconds > BUFFER_CONVERSION_SECONDS
    const ingestEventDirectly = isAnonymousEvent || event.event === '$identify' || !isRecentPerson
    return !ingestEventDirectly
}
