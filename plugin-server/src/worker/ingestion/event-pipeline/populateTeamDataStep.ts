import { PluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { PipelineEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export const tokenOrTeamPresentCounter = new Counter({
    name: 'ingestion_event_hasauthinfo_total',
    help: 'Count of events by presence of the team_id and token field.',
    labelNames: ['team_id_present', 'token_present'],
})

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

    // Collect statistics on the shape of events we are ingesting.
    tokenOrTeamPresentCounter
        .labels({
            team_id_present: event.team_id ? 'true' : 'false',
            token_present: event.token ? 'true' : 'false',
        })
        .inc()
    // statsd copy as prometheus is currently not supported in worker threads.
    runner.hub.statsd?.increment('ingestion_event_hasauthinfo', {
        team_id_present: event.team_id ? 'true' : 'false',
        token_present: event.token ? 'true' : 'false',
    })

    // If a team_id is present (event captured from an app), trust it and return the event as is.
    if (event.team_id) {
        return event as PluginEvent
    }

    // Events with no token or team_id are dropped, they should be blocked by capture
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
    }

    return event as PluginEvent
}
