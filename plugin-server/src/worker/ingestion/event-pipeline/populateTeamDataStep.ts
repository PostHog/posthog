import { PluginEvent } from '@posthog/plugin-scaffold'
import { Counter } from 'prom-client'

import { eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { PipelineEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

export const teamResolutionChecksCounter = new Counter({
    name: 'ingestion_team_resolution_checks_total',
    help: 'Temporary metric to compare the team_id resolved by ingestion and capture. Tagged by result of the check.',
    labelNames: ['check_ok'],
})

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
     *
     * If the event already has a team_id field set by capture, it is used, but plugin-server still runs
     * the resolution logic to confirm no inconsistency exists. Once team_id resolution is fully removed
     * from capture, that section should be resolved, and team_id not trusted anymore.
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

    // If a team_id is present (resolved at capture, or injected by an app), trust it but
    // try resolving from the token if present, and compare results to detect inconsistencies.
    // TODO: remove after lightweight capture is fully rolled-out and the
    //       ingestion_event_hasauthinfo metric confirms all incoming events have a token.
    if (event.team_id) {
        if (event.token) {
            const team = await runner.hub.teamManager.getTeamByToken(event.token)
            const checkOk = team?.id === event.team_id ? 'true' : 'false'
            teamResolutionChecksCounter.labels({ check_ok: checkOk }).inc()
            // statsd copy as prometheus is currently not supported in worker threads.
            runner.hub.statsd?.increment('ingestion_team_resolution_checks', { check_ok: checkOk })
        }
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
        ip: team.anonymize_ips ? null : event.ip,
    }

    return event as PluginEvent
}
