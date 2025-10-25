import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { percentage } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelStepWithConversionMetrics } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { funnelPersonsModalLogic } from '../funnelPersonsModalLogic'
import { funnelTooltipLogic } from '../funnelTooltipLogic'

export interface StepBarProps {
    step: FunnelStepWithConversionMetrics
    series: FunnelStepWithConversionMetrics
    stepIndex: number
    showPersonsModal: boolean
}
interface StepBarCSSProperties extends React.CSSProperties {
    '--series-color': string
    '--conversion-rate': string
}
export function StepBar({ step, stepIndex, series, showPersonsModal }: StepBarProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { getFunnelsColor } = useValues(funnelDataLogic(insightProps))
    const { showTooltip, hideTooltip } = useActions(funnelTooltipLogic(insightProps))
    const { openPersonsModalForSeries } = useActions(funnelPersonsModalLogic(insightProps))

    const ref = useRef<HTMLDivElement | null>(null)

    return (
        <div
            className={clsx('StepBar', !showPersonsModal && 'StepBar__unclickable')}
            /* eslint-disable-next-line react/forbid-dom-props */
            style={
                {
                    '--series-color': getFunnelsColor(series),
                    '--conversion-rate': percentage(series.conversionRates.fromBasisStep, 1, true),
                } as StepBarCSSProperties
            }
            ref={ref}
            onMouseEnter={() => {
                if (ref.current) {
                    const rect = ref.current.getBoundingClientRect()
                    showTooltip([rect.x, rect.y, rect.width], stepIndex, series)
                }
            }}
            onMouseLeave={() => hideTooltip()}
        >
            <div
                className="StepBar__backdrop"
                onClick={
                    showPersonsModal ? () => openPersonsModalForSeries({ step, series, converted: false }) : undefined
                }
            />
            <div
                className="StepBar__fill"
                onClick={
                    showPersonsModal ? () => openPersonsModalForSeries({ step, series, converted: true }) : undefined
                }
            />
        </div>
    )
}
