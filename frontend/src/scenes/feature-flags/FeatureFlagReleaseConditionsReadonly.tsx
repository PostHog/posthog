import { useValues } from 'kea'

import { LemonLabel, LemonTag } from '@posthog/lemon-ui'

import { FeatureFlagEvaluationRuntime, FeatureFlagFilters } from '~/types'

import { FeatureFlagConditionSetCard } from 'products/feature_flags/frontend/FeatureFlagConditionSetCard'
import { FractionalRolloutWarning } from 'products/feature_flags/frontend/FractionalRolloutWarning'

import { EarlyExitIndicator } from './EarlyExitIndicator'
import { FeatureFlagConditionWarning } from './FeatureFlagConditionWarning'
import { FeatureFlagNoConditionsWarning } from './FeatureFlagNoConditionsWarning'
import { featureFlagReleaseConditionsLogic } from './featureFlagReleaseConditionsLogic'

interface FeatureFlagReleaseConditionsReadonlyProps {
    id: string
    filters: FeatureFlagFilters
    isDisabled?: boolean
    evaluationRuntime?: FeatureFlagEvaluationRuntime
}

export function FeatureFlagReleaseConditionsReadonly({
    id,
    filters,
    isDisabled,
    evaluationRuntime,
}: FeatureFlagReleaseConditionsReadonlyProps): JSX.Element {
    // Use readOnly: true to prevent the logic from triggering blast radius API calls.
    // In readonly mode, we don't need live blast radius calculations - the display is static.
    const releaseConditionsLogic = featureFlagReleaseConditionsLogic({
        id,
        readOnly: true,
        filters,
    })

    const { filterGroups, aggregationTargetName, properties, getDistinctIdName, getFlagKey } =
        useValues(releaseConditionsLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <LemonLabel>Release conditions</LemonLabel>
                {isDisabled && (
                    <LemonTag type="muted" size="small">
                        Flag disabled – returns false regardless of conditions
                    </LemonTag>
                )}
            </div>

            <p className="text-xs text-muted mb-2">
                Condition sets are evaluated top to bottom — the first match wins.
            </p>

            {filters.early_exit && <EarlyExitIndicator />}

            <FeatureFlagConditionWarning properties={properties} evaluationRuntime={evaluationRuntime} />

            <FractionalRolloutWarning filterGroups={filterGroups} />

            <div className={isDisabled ? 'opacity-60' : ''}>
                {filterGroups.map((group, index) => (
                    <div key={group.sort_key ?? index}>
                        {index > 0 && (
                            <div className="condition-set-separator my-2 py-0 text-center text-xs font-semibold text-muted">
                                OR
                            </div>
                        )}
                        <FeatureFlagConditionSetCard
                            group={group}
                            index={index}
                            aggregationTargetName={aggregationTargetName(group.aggregation_group_type_index)}
                            getDistinctIdName={getDistinctIdName}
                            getFlagKey={getFlagKey}
                        />
                    </div>
                ))}

                <FeatureFlagNoConditionsWarning conditionSetCount={filterGroups.length} />
            </div>
        </div>
    )
}
