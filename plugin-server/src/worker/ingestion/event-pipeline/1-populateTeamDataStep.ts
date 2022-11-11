import { PipelineEvent } from '../../../types'

import { EventPipelineRunner, StepResult } from './runner'

export async function populateTeamDataStep(
    runner: EventPipelineRunner,
    event: PipelineEvent,
): Promise<StepResult> {
    if (event.team_id) {
        return runner.nextStep('emitToBufferStep', event)
    }

    if (!event.token) {
        runner.hub.statsd?.increment('dropped_event_with_no_team', { token_set: 'false' })
        return null
    }

    const team = await runner.hub.teamManager.fetchTeam(null, event.token)
    if (!team) {
        runner.hub.statsd?.increment('dropped_event_with_no_team', { token_set: 'true' })
        return null
    }

    event = {
        ...event,
        team_id: team.id,
        ip: team.anonymize_ips ? null : event.ip,
    }

    // TODO: handle feature flags


    return runner.nextStep('emitToBufferStep', event)
}
