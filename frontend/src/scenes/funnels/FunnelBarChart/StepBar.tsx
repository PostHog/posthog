import { useActions, useValues } from 'kea'
import { useRef } from 'react'
import { funnelLogic } from '../funnelLogic'
import { FunnelStepWithConversionMetrics } from '~/types'
import { percentage } from 'lib/utils'
import { getSeriesColor } from 'lib/colors'
import clsx from 'clsx'

export interface StepBarProps {
    step: FunnelStepWithConversionMetrics
    series: FunnelStepWithConversionMetrics
    stepIndex: number
}
interface StepBarCSSProperties extends React.CSSProperties {
    '--series-color': string
    '--conversion-rate': string
}
export function StepBar({ step, stepIndex, series }: StepBarProps): JSX.Element {
    const { openPersonsModalForSeries, showTooltip, hideTooltip } = useActions(funnelLogic)
    const { disableFunnelBreakdownBaseline, canOpenPersonModal } = useValues(funnelLogic)

    const ref = useRef<HTMLDivElement | null>(null)

    const seriesOrderForColor = disableFunnelBreakdownBaseline ? (series.order ?? 0) + 1 : series.order ?? 0

    return (
        <div
            className={clsx('StepBar', !canOpenPersonModal && 'StepBar__unclickable')}
            /* eslint-disable-next-line react/forbid-dom-props */
            style={
                {
                    '--series-color': getSeriesColor(seriesOrderForColor),
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
                    canOpenPersonModal ? () => openPersonsModalForSeries({ step, series, converted: false }) : undefined
                }
            />
            <div
                className="StepBar__fill"
                onClick={
                    canOpenPersonModal ? () => openPersonsModalForSeries({ step, series, converted: true }) : undefined
                }
            />
        </div>
    )
}
