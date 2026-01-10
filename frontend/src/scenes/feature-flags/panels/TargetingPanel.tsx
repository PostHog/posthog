import { useActions, useValues } from 'kea'

import { FeatureFlagReleaseConditions } from '../FeatureFlagReleaseConditions'
import { featureFlagLogic } from '../featureFlagLogic'

export function TargetingPanel(): JSX.Element {
    const { featureFlag } = useValues(featureFlagLogic)
    const { setFeatureFlagFilters } = useActions(featureFlagLogic)

    return (
        <div>
            <FeatureFlagReleaseConditions
                id={`${featureFlag.id}`}
                filters={featureFlag.filters}
                onChange={setFeatureFlagFilters}
                evaluationRuntime={featureFlag.evaluation_runtime}
            />
        </div>
    )
}
