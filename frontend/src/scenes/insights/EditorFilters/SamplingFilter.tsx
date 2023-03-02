import { EditorFilterProps } from '~/types'
import './LifecycleToggles.scss'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { IconInfo } from 'lib/lemon-ui/icons'
import { AVAILABLE_SAMPLING_PERCENTAGES, samplingFilterLogic } from './samplingFilterLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function SamplingFilter({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const logic = samplingFilterLogic({ insightType: filters.insight, insightProps })

    const { setSamplingPercentage } = useActions(logic)
    const { samplingPercentage, samplingAvailable } = useValues(logic)

    if (samplingAvailable) {
        return (
            <>
                <span>
                    <b>Sampling percentage</b>{' '}
                    <Tooltip
                        title="Sampling computes the result on only a subset of the data, making insights load significantly
                            faster."
                    >
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
