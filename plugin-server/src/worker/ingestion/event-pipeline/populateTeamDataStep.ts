import { PluginEvent } from '@posthog/plugin-scaffold'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { Hub, PipelineEvent, Team } from '../../../types'
import { sanitizeString } from '../../../utils/db/utils'
import { UUID } from '../../../utils/utils'
import { captureIngestionWarning } from '../utils'
import { tokenOrTeamPresentCounter } from './metrics'

export async function populateTeamDataStep(
    hub: Hub,
    event: PipelineEvent
): Promise<{ eventWithTeam: PluginEvent; team: Team; token: string | undefined } | null> {
    /**
     * Implements team_id resolution and applies the team's ingestion settings (dropping event.ip if requested).
     * Resolution can fail if PG is unavailable, leading to the consumer taking lag until retries succeed.
     *
     * Events captured by apps are directed injected in kafka with a team_id and not token, bypassing capture.
     * For these, we trust the team_id field value.
     */

    const { db } = hub

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
        team = await hub.teamManager.getTeam(event.team_id)
    } else if (event.token) {
        // HACK: we've had null bytes end up in the token in the ingest pipeline before, for some reason. We should try to
        // prevent this generally, but if it happens, we should at least simply fail to lookup the team, rather than crashing
        event.token = sanitizeString(event.token)
        team = await hub.teamManager.getTeamByToken(event.token)
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

    const skipPersonsProcessingForDistinctIds = hub.eventsToSkipPersonsProcessingByToken.get(event.token!)

    const forceOptOutPersonProfiles =
        team.person_processing_opt_out || skipPersonsProcessingForDistinctIds?.includes(event.distinct_id)

    // We allow teams to set the person processing mode on a per-event basis, but override
    // it with the team-level setting, if it's set to opt-out (since this is billing related,
    // we go with preferring not to do the processing even if the event says to do it, if the
    // setting says not to).
    if (forceOptOutPersonProfiles) {
        if (event.properties) {
            event.properties.$process_person_profile = false
        } else {
            event.properties = { $process_person_profile: false }
        }
    }

    const eventWithTeam: PluginEvent = {
        ...event,
        team_id: team.id,
    }

    return { eventWithTeam, team, token: event.token }
}
