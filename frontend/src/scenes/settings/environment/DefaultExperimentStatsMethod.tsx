import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { ExperimentStatsMethod } from '~/types'

import { StatsMethodSelector } from 'products/experiments/frontend/experiments/components/StatsMethodSelector'

import { experimentsConfigLogic } from './experimentsConfigLogic'

export function DefaultExperimentStatsMethod(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const handleChange = (value: ExperimentStatsMethod): void => {
        updateExperimentsConfig({ default_experiment_stats_method: value })
    }

    return (
        <StatsMethodSelector
            value={
                (experimentsConfig?.default_experiment_stats_method as ExperimentStatsMethod) ??
                ExperimentStatsMethod.Bayesian
            }
            onChange={handleChange}
            disabled={!!restrictionReason || experimentsConfigLoading}
            disabledReason={restrictionReason || (experimentsConfigLoading ? 'Loading...' : undefined)}
        />
    )
}
