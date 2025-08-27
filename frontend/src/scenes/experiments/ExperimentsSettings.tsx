import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { OrganizationExperimentStatsMethod } from 'scenes/settings/organization/OrgExperimentStatsMethod'

/**
 * although this works fine for now, if we keep adding more settings we need to refactor this to use the
 * <Settings /> component. That will require we createa a new section for experimets on the SettingsMap.
 */
export function ExperimentsSettings(): JSX.Element {
    return (
        <div className="space-y-8">
            <div>
                <h2 className="mb-2">Statistical method</h2>
                <p className="mb-4 text-secondary">
                    Choose the default statistical method for experiment analysis. This setting applies to all new
                    experiments in your organization and can be overridden per experiment.
                </p>
                <div className="flex flex-col space-y-2">
                    <LemonLabel className="text-base">Default stats method</LemonLabel>
                    <div>
                        <OrganizationExperimentStatsMethod />
                    </div>
                </div>
            </div>
        </div>
    )
}
