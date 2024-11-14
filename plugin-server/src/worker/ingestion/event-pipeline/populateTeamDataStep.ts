import { PluginEvent } from '@posthog/plugin-scaffold'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { PipelineEvent } from '../../../types'
import { UUID } from '../../../utils/utils'
import { captureIngestionWarning } from '../utils'
import { tokenOrTeamPresentCounter } from './metrics'
import { EventPipelineRunner } from './runner'

export async function populateTeamDataStep(
    runner: EventPipelineRunner,
    event: PipelineEvent
): Promise<PluginEvent | null> {
    /**
     * Implements team_id resolution and applies the team's ingestion settings (dropping event.ip if requested).
     * Resolution can fail if PG is unavailable, leading to the consumer taking lag until retries succeed.
     *
     * Events captured by apps are directed injected in kafka with a team_id and not token, bypassing capture.
     * For these, we trust the team_id field value.
     */

    const { db } = runner.hub

    // Collect statistics on the shape of events we are ingesting.
    tokenOrTeamPresentCounter
        .labels({
            team_id_present: event.team_id ? 'true' : 'false',
            token_present: event.token ? 'true' : 'false',
        })
        .inc()

    let team = null
    // Events with no token or team_id are dropped, they should be blocked by capture
    if (!event.token && !event.team_id) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'no_token',
            })
            .inc()
        return null
    } else if (event.team_id) {
        team = await runner.hub.teamManager.fetchTeam(event.team_id)
    } else if (event.token) {
        team = await runner.hub.teamManager.getTeamByToken(event.token)
    }

    // If the token or team_id does not resolve to an existing team, drop the events.
    if (!team) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_token',
            })
            .inc()
        return null
    }

    // Check for an invalid UUID, which should be blocked by capture, when team_id is present
    if (!UUID.validateString(event.uuid, false)) {
        await captureIngestionWarning(db.kafkaProducer, team.id, 'skipping_event_invalid_uuid', {
            eventUuid: JSON.stringify(event.uuid),
        })
        throw new Error(`Not a valid UUID: "${event.uuid}"`)
    }

    // We allow teams to set the person processing mode on a per-event basis, but override
    // it with the team-level setting, if it's set to opt-out (since this is billing related,
    // we go with preferring not to do the processing even if the event says to do it, if the
    // setting says not to).
    if (team.person_processing_opt_out) {
        if (event.properties) {
            event.properties.$process_person_profile = false
        } else {
            event.properties = { $process_person_profile: false }
        }
    }

    event = {
        ...event,
        team_id: team.id,
    }

    return event as PluginEvent
}
