import { Message } from 'node-rdkafka'

import { TopHogMetricFactory, countOkIf } from '@posthog/ingestion-common/framework/extensions/tophog'
import { drop, ok } from '@posthog/ingestion-common/framework/results'
import { ProcessingStep } from '@posthog/ingestion-common/framework/steps'
import { tokenOrTeamPresentCounter, tokenResolvedAsTeamIdCounter } from '@posthog/ingestion-common/metrics'
import { eventDroppedCounter } from '@posthog/node-common/metrics'
import { PluginEvent } from '@posthog/node-common/plugin-scaffold'
import { TeamManager } from '@posthog/node-common/utils/team-manager'

import { EventHeaders, IncomingEvent, Team } from '~/types'

// TeamManager caches teams by id and by token in one key space, so a numeric token loads the team with that id.
function isResolvedAsTeamId(token: string | undefined, team: Team): boolean {
    return team.api_token !== token
}

export function resolveTeamTopHogMetrics<
    TInput extends { headers: EventHeaders },
    TOutput extends { team: Team },
>(): TopHogMetricFactory<TInput, TOutput>[] {
    return [
        countOkIf(
            'token_resolved_as_team_id',
            (output, input) => isResolvedAsTeamId(input.headers.token, output.team),
            (output) => ({ team_id: String(output.team.id) }),
            { topN: 100 }
        ),
    ]
}

export interface ResolveTeamStepInput {
    message: Message
    headers: EventHeaders
    event: IncomingEvent
}

type ResolveTeamError = { error: true; cause: 'no_token' | 'invalid_token' }
type ResolveTeamSuccess = { error: false; team: Team }
type ResolveTeamResult = ResolveTeamSuccess | ResolveTeamError

async function resolveTeam(
    teamManager: TeamManager,
    token: string | undefined,
    teamId: number | null | undefined
): Promise<ResolveTeamResult> {
    tokenOrTeamPresentCounter
        .labels({
            team_id_present: teamId ? 'true' : 'false',
            token_present: token ? 'true' : 'false',
        })
        .inc()

    // Events with no token are dropped, they should be blocked by capture
    if (!token) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'no_token',
            })
            .inc()
        return { error: true, cause: 'no_token' }
    }

    const team = await teamManager.getTeamByToken(token)
    if (!team) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_token',
            })
            .inc()
        return { error: true, cause: 'invalid_token' }
    }

    if (isResolvedAsTeamId(token, team)) {
        tokenResolvedAsTeamIdCounter.inc()
    }

    return { error: false, team }
}

export function createResolveTeamStep<TInput extends ResolveTeamStepInput>(
    teamManager: TeamManager
): ProcessingStep<TInput, Omit<TInput, 'event'> & { event: PluginEvent; team: Team }> {
    return async function resolveTeamStep(input) {
        const { event: incomingEvent, ...restInput } = input

        const result = await resolveTeam(teamManager, input.headers.token, incomingEvent.event.team_id)

        if (result.error) {
            return drop(result.cause)
        }

        const pluginEvent: PluginEvent = { ...incomingEvent.event, team_id: result.team.id }
        return ok({ ...restInput, event: pluginEvent, team: result.team })
    }
}
