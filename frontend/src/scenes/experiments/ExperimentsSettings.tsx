import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { ExperimentRecalculationTime } from 'scenes/settings/environment/ExperimentRecalculationTime'
import { OrganizationExperimentStatsMethod } from 'scenes/settings/organization/OrgExperimentStatsMethod'

/**
 * although this works fine for now, if we keep adding more settings we need to refactor this to use the
 * <Settings /> component. That will require we create a new section for experiments on the SettingsMap.
 */
export function ExperimentsSettings(): JSX.Element {
    return (
        <div className="space-y-8">
            <div>
                <LemonLabel className="text-base">Default statistical method</LemonLabel>
                <p className="text-secondary mt-2">
                    Choose the default statistical method for experiment analysis. This setting applies to all new
                    experiments in your organization and can be overridden per experiment.
                </p>
                <OrganizationExperimentStatsMethod />
            </div>
            <ExperimentRecalculationTime />
        </div>
    )
}
