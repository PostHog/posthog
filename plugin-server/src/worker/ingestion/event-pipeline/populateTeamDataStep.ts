import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineEvent } from '../../../types'
import { EventPipelineRunner } from './runner'

/* 
This step populates event.team_id and deletes event.ip if needed.
If the event already has a team_id we will not run this step and 
the capture endpoint will have handled this process. This is 
temporary as this step will become the default for all events
when we fully remove this functionality from the capture endpoint.
*/
export async function populateTeamDataStep(runner: EventPipelineRunner, event: PipelineEvent) {
    if (!event.token) {
        runner.hub.statsd?.increment('dropped_event_with_no_team', { token_set: 'false' })
        return null
    }

    const team = await runner.hub.teamManager.getTeamByToken(event.token)

    // should we actually throw here?
    if (!team) {
        runner.hub.statsd?.increment('dropped_event_with_no_team', { token_set: 'true' })
        return null
    }

    event = {
        ...event,
        team_id: team.id,
        ip: team.anonymize_ips ? null : event.ip,
    }

    delete event['token']
    return event as PluginEvent
}
