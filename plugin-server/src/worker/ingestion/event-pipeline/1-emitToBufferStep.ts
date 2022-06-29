import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, IngestionPersonData, TeamId } from '../../../types'
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
    if (event.event === '$snapshot') {
        return runner.nextStep('processPersonsStep', event, undefined)
    }

    const person = await runner.hub.db.fetchPerson(event.team_id, event.distinct_id)

    if (shouldBuffer(runner.hub, event, person, event.team_id)) {
        await runner.hub.eventsProcessor.produceEventToBuffer(event)
        return null
    } else {
        return runner.nextStep('pluginsProcessEventStep', event, person)
    }
}

/** Returns whether the event should be delayed using the event buffer mechanism.
 *
 * Why? Non-anonymous non-$identify events with no exisitng person matching their distinct ID are sent to a buffer.
 * This is so that we can better handle the case where one client uses a fresh distinct ID before another client
 * has managed to send the $identify event aliasing an existing anonymous distinct ID to the fresh distinct ID.
 *
 * See this example scenario:
 * 1. User visits signup page,
 *    in turn frontend captures anonymous `$pageview` for distinct ID `XYZ` (anonymous distinct ID = device ID).
 *    This event gets person ID A.
 * 2. User click signup button, initiating in a backend request,
 *    in turn frontend captures anonymous `$autocapture` (click) for distinct ID `XYZ`
 *    This event gets person ID A.
 * 3. Signup request is processed in the backend,
 *    in turn backend captures identified `signup` for distinct ID `alice@example.com`,
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
    const sendToBuffer = !person && !isAnonymousEvent && event.event !== '$identify'

    if (sendToBuffer) {
        hub.statsd?.increment('conversion_events_buffer_size', { teamId: event.team_id.toString() })
    }

    if (!hub.CONVERSION_BUFFER_ENABLED && !hub.conversionBufferEnabledTeams.has(teamId)) {
        return false
    }

    return sendToBuffer
}
