import { EditorFilterProps } from '~/types'
import { LemonButton, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AVAILABLE_SAMPLING_PERCENTAGES, samplingFilterLogic, SamplingFilterLogicProps } from './samplingFilterLogic'
import posthog from 'posthog-js'

interface SamplingFilterProps extends Omit<EditorFilterProps, 'insight' | 'value'> {
    infoTooltipContent?: string
    setFilters?: SamplingFilterLogicProps['setFilters']
}

const DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT =
    'Sampling computes the result on only a subset of the data, making insights load significantly faster.'

export function SamplingFilter({
    filters,
    insightProps,
    infoTooltipContent,
    setFilters,
}: SamplingFilterProps): JSX.Element {
    const logic = samplingFilterLogic({ insightType: filters.insight, insightProps, setFilters })

    const { setSamplingPercentage } = useActions(logic)

    const { samplingPercentage, samplingAvailable } = useValues(logic)

    if (samplingAvailable) {
        return (
            <>
                <div className="flex items-center gap-1">
                    <LemonLabel
                        info={infoTooltipContent || DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT}
                        infoLink="https://posthog.com/manual/sampling"
                    >
                        Sampling (Beta)
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
                    />
                </div>
                {!!samplingPercentage ? (
                    <div className="SamplingFilter">
                        <div className="flex items-center gap-2">
                            {AVAILABLE_SAMPLING_PERCENTAGES.map((percentage, key) => (
                                <LemonButton
                                    key={key}
                                    type="secondary"
                                    size="small"
                                    active={samplingPercentage === percentage}
                                    onClick={() => {
                                        setSamplingPercentage(percentage)

                                        if (samplingPercentage === percentage) {
                                            posthog.capture('sampling_disabled_on_insight')
                                        } else {
                                            posthog.capture('sampling_percentage_updated', { samplingPercentage })
                                        }
                                    }}
                                >{`${percentage}%`}</LemonButton>
                            ))}
                        </div>
                    </div>
                ) : null}
            </>
        )
    }
    return <></>
}
