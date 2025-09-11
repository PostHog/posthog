import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { Team } from '../../../types'
import { parseEventTimestamp } from '../timestamps'
import { captureIngestionWarning } from '../utils'
import { EventPipelineRunner } from './runner'

export async function dropOldEventsStep(
    runner: EventPipelineRunner,
    event: PluginEvent,
    team: Team
): Promise<PluginEvent | null> {
    // If no drop threshold is set (null) or set to 0, don't drop any events
    // Zero threshold is ignored to protect from misconfiguration bugs
    if (!team.drop_events_older_than_seconds) {
        return event
    }

    const eventTimestamp = parseEventTimestamp(event)
    const now = DateTime.fromISO(event.now)
    const ageInSeconds = now.diff(eventTimestamp, 'seconds').seconds

    // If the event is older than the threshold, drop it
    if (ageInSeconds > team.drop_events_older_than_seconds) {
        await captureIngestionWarning(
            runner.hub.db.kafkaProducer,
            team.id,
            'event_dropped_too_old',
            {
                eventUuid: event.uuid,
                event: event.event,
                distinctId: event.distinct_id,
                eventTimestamp: eventTimestamp.toISO(),
                ageInSeconds: Math.floor(ageInSeconds),
                dropThresholdSeconds: team.drop_events_older_than_seconds,
            },
            { alwaysSend: false }
        )
        return null
    }

    return event
}
