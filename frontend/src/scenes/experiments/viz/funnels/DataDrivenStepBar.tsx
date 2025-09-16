import clsx from 'clsx'
import { useRef } from 'react'
import { percentage } from 'lib/utils'
import { FunnelStepWithConversionMetrics } from '~/types'
import { getSeriesColor } from './funnelDataUtils'
import { useDataDrivenTooltip } from './DataDrivenFunnelBarVertical'

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

export function DataDrivenStepBar({ step: _step, stepIndex, series, showPersonsModal }: StepBarProps): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { showTooltip, hideTooltip } = useDataDrivenTooltip()

    // Get color for this series
    const seriesColor = getSeriesColor(series)

    return (
        <div
            className={clsx('StepBar', !showPersonsModal && 'StepBar__unclickable')}
            /* eslint-disable-next-line react/forbid-dom-props */
            style={
                {
                    '--series-color': seriesColor,
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
                onClick={showPersonsModal ? () => console.log('Open modal for dropped off') : undefined}
            />
            <div
                className="StepBar__fill"
                onClick={showPersonsModal ? () => console.log('Open modal for converted') : undefined}
            />
        </div>
    )
}