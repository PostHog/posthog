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

// context: https://github.com/PostHog/posthog/issues/9182
// TL;DR: events from a recently created non-anonymous person are sent to a buffer
// because their person_id might change. We merge based on the person_id of the anonymous user
// so ingestion is delayed for those events to increase our chances of getting person_id correctly
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
