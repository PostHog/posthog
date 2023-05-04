import { FilterType, InsightLogicProps, QueryEditorFilterProps } from '~/types'
import { LemonButton, LemonLabel, LemonSwitch, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AVAILABLE_SAMPLING_PERCENTAGES, samplingFilterLogic } from './samplingFilterLogic'
import posthog from 'posthog-js'
import { insightVizDataLogic } from '../insightVizDataLogic'

const DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT =
    'Sampling computes the result on only a subset of the data, making insights load significantly faster.'

export function SamplingFilterDataExploration({ insightProps }: QueryEditorFilterProps): JSX.Element {
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    return (
        <SamplingFilter
            insightProps={insightProps}
            setFilters={(filters) => updateQuerySource({ samplingFactor: filters?.sampling_factor })}
        />
    )
}

interface SamplingFilterProps {
    insightProps: InsightLogicProps
    setFilters?: (filters: Pick<FilterType, 'sampling_factor'>) => void
    initialSamplingPercentage?: number | null
    infoTooltipContent?: string
}

export function SamplingFilter({
    insightProps,
    setFilters,
    infoTooltipContent,
    initialSamplingPercentage,
}: SamplingFilterProps): JSX.Element | null {
    const logic = samplingFilterLogic({
        insightProps,
        setFilters,
        initialSamplingPercentage,
    })

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
                        Sampling<LemonTag type="warning">BETA</LemonTag>
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
    return null
}
