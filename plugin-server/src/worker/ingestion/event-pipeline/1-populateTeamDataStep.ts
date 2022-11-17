import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineEvent } from '../../../types'
import { EventPipelineRunner, StepResult } from './runner'

// TRICKY: team_id is optional on PipelineEvent but not for PluginEvent
// Only do the type asserton to PluginEvent having verified team_id exists
export async function populateTeamDataStep(runner: EventPipelineRunner, event: PipelineEvent): Promise<StepResult> {
    if (!event.token) {
        runner.hub.statsd?.increment('dropped_event_with_no_team', { token_set: 'false' })
        return null
    }

    const team = await runner.hub.teamManager.getTeamByToken(event.token)
    if (!team) {
        runner.hub.statsd?.increment('dropped_event_with_no_team', { token_set: 'true' })
        return null
    }

    event = {
        ...event,
        team_id: team.id,
        ip: team.anonymize_ips ? null : event.ip,
    }

    return runner.nextStep('emitToBufferStep', event as PluginEvent)
}
