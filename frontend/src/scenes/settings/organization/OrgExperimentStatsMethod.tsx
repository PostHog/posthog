import { useActions, useValues } from 'kea'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { StatsMethodSelector } from '~/scenes/experiments/components/StatsMethodSelector'
import { organizationLogic } from '~/scenes/organizationLogic'
import { ExperimentStatsMethod } from '~/types'

export function OrganizationExperimentStatsMethod(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    // TODO: This should probably be looking at the Experiment resource access level
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const handleChange = (value: ExperimentStatsMethod): void => {
        updateOrganization({ default_experiment_stats_method: value })
    }

    return (
        <div className="mt-4">
            <StatsMethodSelector
                value={currentOrganization?.default_experiment_stats_method ?? ExperimentStatsMethod.Bayesian}
                onChange={handleChange}
                disabled={!!restrictionReason || currentOrganizationLoading}
                disabledReason={restrictionReason || (currentOrganizationLoading ? 'Loading...' : undefined)}
            />
        </div>
    )
}
