import { EditorFilterProps, InsightType } from '~/types'
import './LifecycleToggles.scss'
import { Link } from '@posthog/lemon-ui'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Slider } from 'antd'
import { IconInfo } from 'lib/lemon-ui/icons'

const INSIGHT_TYPES_WITH_SAMPLING_SUPPORT = new Set([InsightType.LIFECYCLE, InsightType.FUNNELS, InsightType.TRENDS])

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
        editorFilters.insight &&
        INSIGHT_TYPES_WITH_SAMPLING_SUPPORT.has(editorFilters.insight)

    if (insightSupportsSampling) {
        return (
            <>
                <span>
                    <b>Sampling percentage</b>{' '}
                    <Link to="https://posthog.com/manual/sampling" target="_blank">
                        <IconInfo className="text-xl text-muted-alt shrink-0" />
                    </Link>
                </span>
                <div className="SamplingFilter">
                    <Slider
                        defaultValue={100}
                        min={5}
                        max={100}
                        step={5}
                        trackStyle={{ background: 'var(--primary)' }}
                        handleStyle={{ background: 'var(--primary)' }}
                        style={{ maxWidth: 150 }}
                        onAfterChange={(newValue) => {
                            if (editorFilters.insight === InsightType.FUNNELS) {
                                setFunnelFilters({
                                    ...filters,
                                    sampling_factor: newValue / 100,
                                })
                                return
                            }
                            setInsightFilters({
                                ...filters,
                                sampling_factor: newValue / 100,
                            })
                        }}
                        tipFormatter={(value) => `${value}%`}
                    />
                </div>
            </>
        )
    }
    return <></>
}
