import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonLabel, LemonSegmentedButton, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { AVAILABLE_SAMPLING_PERCENTAGES, samplingFilterLogic } from './samplingFilterLogic'

const DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT =
    'Sampling computes the result on only a subset of the data, making insights load significantly faster.'

interface SamplingFilterProps {
    insightProps: InsightLogicProps
    infoTooltipContent?: string
}

function getInsightType(logic: {
    isTrends: boolean
    isFunnels: boolean
    isRetention: boolean
    isPaths: boolean
    isStickiness: boolean
    isLifecycle: boolean
}): string {
    if (logic.isTrends) {
        return 'TRENDS'
    }
    if (logic.isFunnels) {
        return 'FUNNELS'
    }
    if (logic.isRetention) {
        return 'RETENTION'
    }
    if (logic.isPaths) {
        return 'PATHS'
    }
    if (logic.isStickiness) {
        return 'STICKINESS'
    }
    if (logic.isLifecycle) {
        return 'LIFECYCLE'
    }
    return 'UNKNOWN'
}

export function SamplingFilter({ insightProps, infoTooltipContent }: SamplingFilterProps): JSX.Element {
    const { hasDataWarehouseSeries, isTrends, isFunnels, isRetention, isPaths, isStickiness, isLifecycle } = useValues(
        insightVizDataLogic(insightProps)
    )
    const { samplingPercentage } = useValues(samplingFilterLogic(insightProps))
    const { setSamplingPercentage } = useActions(samplingFilterLogic(insightProps))
    const insightType = getInsightType({ isTrends, isFunnels, isRetention, isPaths, isStickiness, isLifecycle })

    return (
        <>
            <div className="flex items-center gap-1">
                <LemonLabel
                    info={infoTooltipContent || DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT}
                    infoLink="https://posthog.com/docs/product-analytics/sampling"
                >
                    Sampling <LemonTag type="warning">BETA</LemonTag>
                </LemonLabel>
                <LemonSwitch
                    className="m-2"
                    onChange={(checked) => {
                        if (checked) {
                            setSamplingPercentage(10)
                            posthog.capture('sampling_enabled_on_insight', { insight_type: insightType })
                            return
                        }
                        setSamplingPercentage(null)
                        posthog.capture('sampling_disabled_on_insight', { insight_type: insightType })
                    }}
                    checked={!!samplingPercentage}
                    disabledReason={
                        hasDataWarehouseSeries ? 'Sampling is not available for data warehouse series' : undefined
                    }
                />
            </div>
            {samplingPercentage ? (
                <div className="SamplingFilter">
                    <div className="flex items-center gap-2">
                        <LemonSegmentedButton
                            options={AVAILABLE_SAMPLING_PERCENTAGES.map((percentage) => ({
                                value: percentage,
                                label: `${percentage}%`,
                            }))}
                            value={samplingPercentage}
                            onChange={(newValue) => {
                                setSamplingPercentage(newValue)

                                posthog.capture('sampling_percentage_updated', { samplingPercentage, insight_type: insightType })
                            }}
                        />
                    </div>
                </div>
            ) : null}
        </>
    )
}
