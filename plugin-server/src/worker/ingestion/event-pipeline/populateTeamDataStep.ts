import { PluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { PipelineEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export const inconsistentTeamCounter = new Counter({
    name: 'ingestion_inconsistent_team_resolution_total',
    help: 'Count of events with an inconsistent team resolution between capture and plugin-server, should be zero.',
})

export async function populateTeamDataStep(
    runner: EventPipelineRunner,
    event: PipelineEvent
): Promise<PluginEvent | null> {
    /**
     * Implements team_id resolution and applies the team's ingestion settings (dropping event.ip if requested).
     *
     * If the event already has a team_id field set by capture, it is used, but plugin-server still runs
     * the resolution logic to confirm no inconsistency exists. Once team_id resolution is fully removed
     * from capture, that section should be resolved, and team_id not trusted anymore.
     */

    // Events ingested with no token are dropped, they should be blocked by capture
    if (!event.token) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'no_token',
            })
            .inc()
        runner.hub.statsd?.increment('dropped_event_with_no_team', { token_set: 'false' })
        return null
    }

    // Team lookup is cached, but will fail if PG is unavailable and the key expired.
    // We should retry processing this event.
    const team = await runner.hub.teamManager.getTeamByToken(event.token)

    // Short-circuit the logic if capture already resolved the team ID,
    // just compare the lookup result to confirm data quality.
    // TODO: remove after lightweight capture is fully rolled-out
    if (event.team_id) {
        if (team?.id || event.team_id) {
            inconsistentTeamCounter.inc()
            runner.hub.statsd?.increment('ingestion_inconsistent_team_resolution_total')
        }
        return event as PluginEvent
    }

    // If the token does not resolve to an existing team, drop the events.
    if (!team) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_token',
            })
            .inc()
        runner.hub.statsd?.increment('dropped_event_with_no_team', { token_set: 'true' })
        return null
    }

    event = {
        ...event,
        team_id: team.id,
        ip: team.anonymize_ips ? null : event.ip,
    }

    return event as PluginEvent
}
