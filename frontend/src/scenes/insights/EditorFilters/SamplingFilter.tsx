import { EditorFilterProps, InsightType } from '~/types'
import './LifecycleToggles.scss'
import { LemonSwitch } from '@posthog/lemon-ui'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function SamplingFilter({ filters: editorFilters, insightProps }: EditorFilterProps): JSX.Element {
    const logic = insightLogic(insightProps)
    const { setFilters } = useActions(logic)
    const { filters } = useValues(logic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Sampling is currently behind a feature flag and only available on lifecycle queries
    const insightSupportsSampling =
        editorFilters.insight === InsightType.LIFECYCLE || editorFilters.insight === InsightType.FUNNELS

    if (featureFlags[FEATURE_FLAGS.SAMPLING] && insightSupportsSampling) {
        return (
            <>
                <div className="SamplingFilter">
                    <LemonSwitch
                        checked={!!filters.sample_results}
                        label={
                            <>
                                <span>Show sampled results</span>
                            </>
                        }
                        onChange={(newChecked) => setFilters({ ...filters, sample_results: newChecked })}
                    />
                </div>
            </>
        )
    }
    return <></>
}
