import { EditorFilterProps, InsightType } from '~/types'
import './LifecycleToggles.scss'
import { LemonSwitch } from '@posthog/lemon-ui'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const DEFAULT_SAMPLING_FACTOR = 0.1

export function SamplingFilter({ filters: editorFilters, insightProps }: EditorFilterProps): JSX.Element {
    const logic = insightLogic(insightProps)
    const { setFilters } = useActions(logic)
    const { filters } = useValues(logic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Sampling is currently behind a feature flag and only available on lifecycle queries
    const insightSupportsSampling =
        editorFilters.insight === InsightType.LIFECYCLE || editorFilters.insight === InsightType.FUNNELS

    if (insightSupportsSampling) {
        return (
            <>
                <div className="SamplingFilter">
                    <LemonSwitch
                        checked={!!filters.sampling_factor}
                        label={
                            <>
                                <span>Show sampled results</span>
                            </>
                        }
                        onChange={(newChecked) => setFilters({ ...filters, sampling_factor: newChecked ? DEFAULT_SAMPLING_FACTOR : null })}
                    />
                </div>
            </>
        )
    }
    return <></>
}
