import { EditorFilterProps } from '~/types'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { IconInfo } from 'lib/lemon-ui/icons'
import { AVAILABLE_SAMPLING_PERCENTAGES, samplingFilterLogic, SamplingFilterLogicProps } from './samplingFilterLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
                <span>
                    <b>Sampling percentage</b>{' '}
                    <Tooltip title={infoTooltipContent || DEFAULT_SAMPLING_INFO_TOOLTIP_CONTENT}>
                        <Link to="https://posthog.com/manual/sampling" target="_blank">
                            <IconInfo className="text-xl text-muted-alt shrink-0" />
                        </Link>
                    </Tooltip>
                </span>
                <div className="SamplingFilter">
                    <div className="flex items-center gap-2">
                        {AVAILABLE_SAMPLING_PERCENTAGES.map((percentage, key) => (
                            <LemonButton
                                key={key}
                                type="secondary"
                                size="small"
                                active={samplingPercentage === percentage}
                                onClick={() => setSamplingPercentage(percentage)}
                            >{`${percentage}%`}</LemonButton>
                        ))}
                    </div>
                </div>
            </>
        )
    }
    return <></>
}
