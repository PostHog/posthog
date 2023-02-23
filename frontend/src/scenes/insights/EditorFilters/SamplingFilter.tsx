import { EditorFilterProps, InsightType } from '~/types'
import './LifecycleToggles.scss'
import { LemonSwitch } from '@posthog/lemon-ui'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

const DEFAULT_SAMPLING_FACTOR = 0.1

export function SamplingFilter({ filters: editorFilters, insightProps }: EditorFilterProps): JSX.Element {
    const initializedInsightLogic = insightLogic(insightProps)
    const initializedFunnelLogic = funnelLogic(insightProps)

    const { setFilters: setInsightFilters } = useActions(initializedInsightLogic)
    const { setFilters: setFunnelFilters } = useActions(initializedFunnelLogic)

    const { filters } = useValues(initializedInsightLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    // Sampling is currently behind a feature flag and only available on lifecycle queries
    const insightSupportsSampling =
        featureFlags[FEATURE_FLAGS.SAMPLING] &&
        (editorFilters.insight === InsightType.LIFECYCLE || editorFilters.insight === InsightType.FUNNELS)

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
                        onChange={(newChecked) => {
                            if (editorFilters.insight === InsightType.FUNNELS) {
                                setFunnelFilters({
                                    ...filters,
                                    sampling_factor: newChecked ? DEFAULT_SAMPLING_FACTOR : null,
                                })
                                return
                            }
                            setInsightFilters({
                                ...filters,
                                sampling_factor: newChecked ? DEFAULT_SAMPLING_FACTOR : null,
                            })
                        }}
                    />
                </div>
            </>
        )
    }
    return <></>
}
