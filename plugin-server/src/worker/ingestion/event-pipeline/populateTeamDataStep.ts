import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { Hub, PipelineEvent, Team } from '../../../types'
import { sanitizeString } from '../../../utils/db/utils'
import { tokenOrTeamPresentCounter } from './metrics'

export async function populateTeamDataStep(
    hub: Pick<Hub, 'teamManager'>,
    event: PipelineEvent
): Promise<{ event: PipelineEvent; team: Team } | null> {
    /**
     * Implements team_id resolution and applies the team's ingestion settings (dropping event.ip if requested).
     * Resolution can fail if PG is unavailable, leading to the consumer taking lag until retries succeed.
     *
     * Events captured by apps are directed injected in kafka with a team_id and not token, bypassing capture.
     * For these, we trust the team_id field value.
     */

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
        // TODO: do we still need this? we also sanitize this token in `normalizeEvent` which is called in `parseKafkaBatch`
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

    return { event, team }
}
