import { isDevEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'
import { dlq, drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { metricMessageDlqCounter, metricMessageDroppedCounter } from './metrics'

export function createResolveMetricsTeamStep<T extends { token: string }>(
    teamManager: Pick<TeamManager, 'getTeam' | 'getTeamByToken'>
): ProcessingStep<T, T & { teamId: number }> {
    return async function resolveMetricsTeamStep(input) {
        let team
        try {
            if (isDevEnv() && input.token === 'phc_local') {
                // phc_local is a special token used in dev to refer to team 1
                team = await teamManager.getTeam(1)
            } else {
                team = await teamManager.getTeamByToken(input.token)
            }
        } catch (e) {
            // A lookup failure is an infrastructure fault, not a bad message: keep it replayable.
            logger.error('team_lookup_error', { error: e })
            metricMessageDlqCounter.inc({ reason: 'team_lookup_error', team_id: 'unknown' })
            return dlq('team_lookup_error', e)
        }

        if (!team) {
            logger.error('team_not_found', { token_with_no_team: input.token })
            metricMessageDroppedCounter.inc({ reason: 'team_not_found', team_id: 'unknown' })
            return drop('team_not_found')
        }

        return ok({ ...input, teamId: team.id })
    }
}
