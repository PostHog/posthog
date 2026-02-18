import { useActions, useValues } from 'kea'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { StatsMethodSelector } from '~/scenes/experiments/components/StatsMethodSelector'
import { teamLogic } from '~/scenes/teamLogic'
import { ExperimentStatsMethod } from '~/types'

export function DefaultExperimentStatsMethod(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    // TODO: This should probably be looking at the Experiment resource access level
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const handleChange = (value: ExperimentStatsMethod): void => {
        updateCurrentTeam({ default_experiment_stats_method: value })
    }

    return (
        <StatsMethodSelector
            value={currentTeam?.default_experiment_stats_method ?? ExperimentStatsMethod.Bayesian}
            onChange={handleChange}
            disabled={!!restrictionReason || currentTeamLoading}
            disabledReason={restrictionReason || (currentTeamLoading ? 'Loading...' : undefined)}
        />
    )
}
