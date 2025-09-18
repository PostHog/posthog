import clsx from 'clsx'
import { useRef, useState } from 'react'

import { percentage } from 'lib/utils'

import { FunnelStepWithConversionMetrics } from '~/types'

import { useTooltip } from './FunnelBarVertical'
import { useFunnelChartData } from './FunnelChart'
import { SampledSessionsModal } from './SampledSessionsModal'
import { getSeriesColor } from './funnelUtils'

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
    const ref = useRef<HTMLDivElement | null>(null)
    const { showTooltip, hideTooltip } = useTooltip()
    const { experimentResult } = useFunnelChartData()
    const [isModalOpen, setIsModalOpen] = useState(false)

    const seriesColor = getSeriesColor(series)

    // Get sampled sessions from the experiment result
    // Find the variant result that matches this series
    let stepsEventData: Array<Array<[string, string]>> | undefined
    if (experimentResult) {
        const variantKey = series.breakdown_value
        if (variantKey === 'control') {
            stepsEventData = experimentResult.baseline?.steps_event_data as Array<Array<[string, string]>> | undefined
        } else {
            const variantResult = experimentResult.variant_results?.find((v: any) => v.key === variantKey)
            stepsEventData = variantResult?.steps_event_data as Array<Array<[string, string]>> | undefined
        }
    }
    const hasRecordings = stepsEventData && stepsEventData[stepIndex]?.length > 0

    const handleClick = (): void => {
        if (hasRecordings) {
            setIsModalOpen(true)
        }
    }

    return (
        <>
            <div
                className={clsx('StepBar', !hasRecordings && 'StepBar__unclickable')}
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
                        showTooltip([rect.x, rect.y, rect.width], stepIndex, series, !!hasRecordings)
                    }
                }}
                onMouseLeave={() => hideTooltip()}
            >
                <div
                    className="StepBar__backdrop"
                    onClick={handleClick}
                    style={{ cursor: hasRecordings ? 'pointer' : 'default' }}
                />
                <div
                    className="StepBar__fill"
                    onClick={handleClick}
                    style={{ cursor: hasRecordings ? 'pointer' : 'default' }}
                />
            </div>

            {isModalOpen && stepsEventData && (
                <SampledSessionsModal
                    isOpen={isModalOpen}
                    onClose={() => setIsModalOpen(false)}
                    stepsEventData={stepsEventData}
                    stepNames={[step.name]}
                    variant={String(series.breakdown_value || 'control')}
                />
            )}
        </>
    )
}
