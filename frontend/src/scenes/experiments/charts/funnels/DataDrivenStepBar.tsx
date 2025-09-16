import { useRef } from 'react'

import { percentage } from 'lib/utils'

import { FunnelStepWithConversionMetrics } from '~/types'

import { useDataDrivenTooltip } from './DataDrivenFunnelBarVertical'
import { getSeriesColor } from './funnelDataUtils'

export interface StepBarProps {
    step: FunnelStepWithConversionMetrics
    series: FunnelStepWithConversionMetrics
    stepIndex: number
}

interface StepBarCSSProperties extends React.CSSProperties {
    '--series-color': string
    '--conversion-rate': string
}

export function DataDrivenStepBar({ stepIndex, series }: StepBarProps): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { showTooltip, hideTooltip } = useDataDrivenTooltip()

    const seriesColor = getSeriesColor(series)

    return (
        <div
            className="StepBar StepBar__unclickable"
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
            <div className="StepBar__backdrop" />
            <div className="StepBar__fill" />
        </div>
    )
}
