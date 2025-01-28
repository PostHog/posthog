import { LemonLabel, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { InsightLogicProps } from '~/types'

import { AVAILABLE_SAMPLING_PERCENTAGES, poeFilterLogic } from './poeFilterLogic'

const DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT =
    'Sampling computes the result on only a subset of the data, making insights load significantly faster.'

interface PoeFilterProps {
    insightProps: InsightLogicProps
    infoTooltipContent?: string
}

export function PoeFilter({ insightProps, infoTooltipContent }: PoeFilterProps): JSX.Element {
    const { poeMode } = useValues(poeFilterLogic(insightProps))
    const { setPoeMode } = useActions(poeFilterLogic(insightProps))

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
                            setPoeMode('person_id_override_properties_on_events')
                        } else {
                            setPoeMode(undefined)
                        }
                    }}
                    checked={poeMode !== undefined}
                />
            </div>
            {poeMode !== undefined ? (
                <div className="SamplingFilter">
                    <div className="flex items-center gap-2">
                        <LemonSegmentedButton
                            options={AVAILABLE_SAMPLING_PERCENTAGES.map((percentage) => ({
                                value: percentage,
                                label: `${percentage}%`,
                            }))}
                            value={10}
                            onChange={(newValue) => {
                                // setSamplingPercentage(newValue)
                                // posthog.capture('sampling_percentage_updated', { samplingPercentage })
                                console.log(newValue)
                            }}
                        />
                    </div>
                </div>
            ) : null}
        </>
    )
}
