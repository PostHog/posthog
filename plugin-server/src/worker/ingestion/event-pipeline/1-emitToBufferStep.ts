import { PluginEvent } from '@posthog/plugin-scaffold'

import { KAFKA_BUFFER } from '../../../config/kafka-topics'
import { Hub, IngestionPersonData, TeamId } from '../../../types'
import { status } from '../../../utils/status'
import { LazyPersonContainer } from '../lazy-person-container'
import { EventPipelineRunner, StepResult } from './runner'

export async function emitToBufferStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    shouldBuffer: (
        hub: Hub,
        event: PluginEvent,
        person: IngestionPersonData | undefined,
        teamId: TeamId
    ) => boolean = shouldSendEventToBuffer
): Promise<StepResult> {
    status.debug('🔁', 'Running emitToBufferStep', { event })
    const personContainer = new LazyPersonContainer(event.team_id, event.distinct_id, runner.hub)

    if (event.event === '$snapshot') {
        return runner.nextStep('processPersonsStep', event, personContainer)
    }

    const person = await personContainer.get()
    if (shouldBuffer(runner.hub, event, person, event.team_id)) {
        const processEventAt = Date.now() + runner.hub.BUFFER_CONVERSION_SECONDS * 1000
        status.debug('🔁', 'Emitting event to buffer', { event, processEventAt })

        await runner.hub.kafkaProducer.queueMessage({
            topic: KAFKA_BUFFER,
            messages: [
                {
                    key: event.team_id.toString(),
                    value: JSON.stringify(event),
                    headers: { processEventAt: processEventAt.toString(), eventId: event.uuid },
                },
            ],
        })

        // ensure we flush the producer to ensure that the offset for the main
        // topis is only updated after we have confirmation that the message has
        // been flushed.
        // NOTE: we do not actually check the response of the flush, thus we do
        // not actually check for success of the message being delivered to
        // Kafka. It is not trivial atm to handle this case as there will be any
        // number of messages in the response, not just the message referenced
        // in this method.
        // NOTE: calling flush on every call isn't optimal although we can
        // optimize later.
        // TODO: handle ack of the specific message from this method or
        // otherwise send to DLQ or appropriate. i.e. we don't have guaranteed
        // delivery atm.
        await runner.hub.kafkaProducer.flush()

        runner.hub.statsd?.increment('events_sent_to_buffer')
        return null
    } else {
        return runner.nextStep('pluginsProcessEventStep', event, personContainer)
    }
}

/** Returns whether the event should be delayed using the event buffer mechanism.
 *
 * Why? Non-anonymous non-$identify events with no existing person matching their distinct ID are sent to a buffer.
 * This is so that we can better handle the case where one client uses a fresh distinct ID before another client
 * has managed to send the $identify event aliasing an existing anonymous distinct ID to the fresh distinct ID.
 *
 * This is easier to see with an example scenario:
 * 1. User visits signup page,
 *    in turn frontend captures anonymous `$pageview` for distinct ID `XYZ` (anonymous distinct ID = device ID).
 *    This event gets person ID A.
 * 2. User click signup button, initiating in a backend request,
 *    in turn frontend captures anonymous `$autocapture` (click) for distinct ID `XYZ`.
 *    This event gets person ID A.
 * 3. Signup request is processed in the backend,
 *    in turn backend captures identified `signup` for distinct ID `alice@example.com`.
 *    OOPS! We haven't seen `alice@example.com` before, so this event gets person ID B.
 * 4. Signup request finishes successfully,
 *    in turn frontend captures identified `$identify` aliasing distinct ID `XYZ` to `alice@example.com`.
 *    This event gets person ID A.
 *
 * Without a buffer, the event from step 3 gets a new person ID, which messes up analysis by unique users.
 * By delaying the event from step 3, all events get the desired person ID A.
 *
 * More context: https://github.com/PostHog/posthog/issues/9182
 */
export function shouldSendEventToBuffer(
    hub: Hub,
    event: PluginEvent,
    person: IngestionPersonData | undefined,
    teamId: TeamId
): boolean {
    const isAnonymousEvent =
        event.properties && event.properties['$device_id'] && event.distinct_id === event.properties['$device_id']

    // We do not send events from mobile libraries to the buffer because:
    // a) that wouldn't help with the backend problem outlined above
    // b) because of issues with $device_id in the mobile libraries, we often mislabel events
    //  as being from an identified user when in fact they are not, leading to unnecessary buffering
    const isMobileLibrary =
        !!event.properties &&
        ['posthog-ios', 'posthog-android', 'posthog-react-native', 'posthog-flutter'].includes(event.properties['$lib'])
    const sendToBuffer = !isMobileLibrary && !person && !isAnonymousEvent && event.event !== '$identify'

    if (sendToBuffer) {
        hub.statsd?.increment('conversion_events_buffer_size', { teamId: event.team_id.toString() })
    }

    if (!hub.CONVERSION_BUFFER_ENABLED && !hub.conversionBufferEnabledTeams.has(teamId)) {
        return false
    }

    return sendToBuffer
}
