import { useActions, useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

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
        <div>
            <div className="flex flex-col space-y-2">
                <LemonLabel className="text-base">Default statistical method</LemonLabel>
                <p className="text-secondary">
                    Choose the default statistical method for experiment analysis. This setting applies to all new
                    experiments in your organization and can be overridden per experiment.
                </p>
                <div>
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
                </div>
            </div>
        </div>
    )
}
