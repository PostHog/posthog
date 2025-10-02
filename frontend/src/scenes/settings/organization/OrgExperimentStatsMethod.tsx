import { useActions, useValues } from 'kea'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

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
        <LemonSelect
            value={currentOrganization?.default_experiment_stats_method ?? ExperimentStatsMethod.Bayesian}
            onChange={handleChange}
            options={[
                {
                    value: ExperimentStatsMethod.Bayesian,
                    label: 'Bayesian',
                    labelInMenu: (
                        <div>
                            <div>Bayesian</div>
                        </div>
                    ),
                },
                {
                    value: ExperimentStatsMethod.Frequentist,
                    label: 'Frequentist',
                    labelInMenu: (
                        <div>
                            <div>Frequentist</div>
                        </div>
                    ),
                },
            ]}
            disabledReason={restrictionReason || (currentOrganizationLoading ? 'Loading...' : undefined)}
            data-attr="organization-experiment-stats-method"
        />
    )
}
