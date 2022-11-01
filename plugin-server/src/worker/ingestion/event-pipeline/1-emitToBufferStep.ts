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
    status.debug('🔁', 'Running emitToBufferStep', { event: event.event, distinct_id: event.distinct_id })
    const personContainer = new LazyPersonContainer(event.team_id, event.distinct_id, runner.hub)

    if (event.event === '$snapshot') {
        return runner.nextStep('processPersonsStep', event, personContainer)
    }

    const person = await personContainer.get()
    if (shouldBuffer(runner.hub, event, person, event.team_id)) {
        const processEventAt = Date.now() + runner.hub.BUFFER_CONVERSION_SECONDS * 1000
        status.debug('🔁', 'Emitting event to buffer', {
            event: event.event,
            eventId: event.uuid,
            processEventAt,
        })

        // TODO: handle delaying offset commit for this message, according to
        // producer acknowledgement. It's a little tricky as it stands as we do
        // not have the a reference to resolveOffset here. Rather than do a
        // refactor I'm just going to let this hang and resolve as a followup.
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
    // Libraries by default create a unique id for this `type-name_value` for $groupidentify,
    // we don't want to buffer these to make group properties available asap
    // identify and alias are identical and could merge the person - the sooner we update the person_id the better
    const isIdentifyingEvent =
        event.event == '$groupidentify' || event.event == '$identify' || event.event == `$create_alias`

    const isAnonymousEvent =
        event.properties && event.properties['$device_id'] && event.distinct_id === event.properties['$device_id']

    // We do not send events from mobile libraries to the buffer because:
    // a) that wouldn't help with the backend problem outlined above
    // b) because of issues with $device_id in the mobile libraries, we often mislabel events
    //  as being from an identified user when in fact they are not, leading to unnecessary buffering
    const isMobileLibrary =
        !!event.properties &&
        ['posthog-ios', 'posthog-android', 'posthog-react-native', 'posthog-flutter'].includes(event.properties['$lib'])

    const sendToBuffer = !isMobileLibrary && !person && !isAnonymousEvent && !isIdentifyingEvent

    if (sendToBuffer) {
        hub.statsd?.increment('conversion_events_buffer_size', { teamId: event.team_id.toString() })
    }

    if (!hub.CONVERSION_BUFFER_ENABLED && !hub.conversionBufferEnabledTeams.has(teamId)) {
        status.debug('🔁', 'Conversion buffer disabled, not sending event to buffer', { event, person })
        return false
    }

    return sendToBuffer
}
