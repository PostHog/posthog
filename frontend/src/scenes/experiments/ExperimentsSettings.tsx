import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { OrganizationExperimentRecalculationTime } from 'scenes/settings/organization/OrgExperimentRecalculationTime'
import { OrganizationExperimentStatsMethod } from 'scenes/settings/organization/OrgExperimentStatsMethod'

import { experimentLogic } from './experimentLogic'

/**
 * although this works fine for now, if we keep adding more settings we need to refactor this to use the
 * <Settings /> component. That will require we create a new section for experiments on the SettingsMap.
 */
export function ExperimentsSettings(): JSX.Element {
    const { featureFlags } = useValues(experimentLogic)
    const timeseriesEnabled = featureFlags[FEATURE_FLAGS.EXPERIMENT_TIMESERIES]

    return (
        <div className="space-y-8">
            <OrganizationExperimentStatsMethod />
            {timeseriesEnabled && <OrganizationExperimentRecalculationTime />}
        </div>
    )
}
