import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { Hub, PipelineEvent, Team } from '../../types'
import { tokenOrTeamPresentCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

type ResolveTeamError = { error: true; cause: 'no_token' | 'invalid_token' }
type ResolveTeamSuccess = { error: false; team: Team }
type ResolveTeamResult = ResolveTeamSuccess | ResolveTeamError

async function resolveTeam(hub: Pick<Hub, 'teamManager'>, event: PipelineEvent): Promise<ResolveTeamResult> {
    tokenOrTeamPresentCounter
        .labels({
            team_id_present: event.team_id ? 'true' : 'false',
            token_present: event.token ? 'true' : 'false',
        })
        .inc()

    // Events with no token are dropped, they should be blocked by capture
    if (!event.token) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'no_token',
            })
            .inc()
        return { error: true, cause: 'no_token' }
    }

    const team = await hub.teamManager.getTeamByToken(event.token)
    if (!team) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_token',
            })
            .inc()
        return { error: true, cause: 'invalid_token' }
    }

    return {
        error: false,
        team,
    }
}

export function createResolveTeamStep<T extends { event: PipelineEvent }>(
    hub: Hub
): ProcessingStep<T, T & { team: Team }> {
    return async function resolveTeamStep(input) {
        const { event } = input

        const result = await resolveTeam(hub, event)

        if (result.error) {
            return drop(result.cause)
        }

        return ok({ ...input, team: result.team })
    }
}
