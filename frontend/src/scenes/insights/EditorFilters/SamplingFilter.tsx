import { EditorFilterProps, InsightType } from '~/types'
import './LifecycleToggles.scss'
import { LemonSwitch } from '@posthog/lemon-ui'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function SamplingFilter({ filters: editorFilters }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(insightLogic)
    const { filters } = useValues(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Sampling is currently behind a feature flag and only available on lifecycle queries
    if (!featureFlags[FEATURE_FLAGS.SAMPLING] || editorFilters.insight !== InsightType.LIFECYCLE) {
        return <></>
    }
    return (
        <>
            <div className="SamplingFilter">
                <LemonSwitch
                    checked={!!filters.sample_results}
                    label={
                        <>
                            <span>Turn on sampling</span>
                        </>
                    }
                    onChange={(newChecked) => setFilters({ ...filters, sample_results: newChecked })}
                />
            </div>
        </>
    )
}
