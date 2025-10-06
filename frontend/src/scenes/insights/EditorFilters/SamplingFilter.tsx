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

export function SamplingFilter({ insightProps, infoTooltipContent }: SamplingFilterProps): JSX.Element {
    const { hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightProps))
    const { samplingPercentage } = useValues(samplingFilterLogic(insightProps))
    const { setSamplingPercentage } = useActions(samplingFilterLogic(insightProps))

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
                            posthog.capture('sampling_enabled_on_insight')
                            return
                        }
                        setSamplingPercentage(null)
                        posthog.capture('sampling_disabled_on_insight')
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

                                posthog.capture('sampling_percentage_updated', { samplingPercentage })
                            }}
                        />
                    </div>
                </div>
            ) : null}
        </>
    )
}
