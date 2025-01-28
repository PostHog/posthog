import { LemonLabel, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { AVAILABLE_SAMPLING_PERCENTAGES, poeFilterLogic } from './poeFilterLogic'

const DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT =
    'Sampling computes the result on only a subset of the data, making insights load significantly faster.'

interface PoeFilterProps {
    insightProps: InsightLogicProps
    infoTooltipContent?: string
}

export function PoeFilter({ insightProps, infoTooltipContent }: PoeFilterProps): JSX.Element {
    const { isDataWarehouseSeries } = useValues(insightVizDataLogic(insightProps))
    const { samplingPercentage } = useValues(poeFilterLogic(insightProps))
    const { setSamplingPercentage } = useActions(poeFilterLogic(insightProps))

    return (
        <>
            <div className="flex items-center gap-1">
                <LemonLabel
                    info={infoTooltipContent || DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT}
                    infoLink="https://posthog.com/docs/product-analytics/sampling"
                >
                    Override Person Properties Mode
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
                        isDataWarehouseSeries ? 'Sampling is not available for data warehouse series' : undefined
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
