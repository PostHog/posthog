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
    stepIndex: number
}

interface StepBarCSSProperties extends React.CSSProperties {
    '--series-color': string
    '--conversion-rate': string
}

export function StepBar({ step, stepIndex }: StepBarProps): JSX.Element {
    const ref = useRef<HTMLDivElement | null>(null)
    const { showTooltip, hideTooltip } = useTooltip()
    const { experimentResult } = useFunnelChartData()
    const [isModalOpen, setIsModalOpen] = useState(false)

    const seriesColor = getSeriesColor(step)

    // Get sampled sessions from the experiment result
    // Find the variant result that matches this series
    let stepsEventData: Array<[string, string]> | undefined
    let prevStepsEventData: Array<[string, string]> | undefined
    if (experimentResult) {
        const variantKey = step.breakdown_value
        if (variantKey === 'control') {
            stepsEventData = experimentResult.baseline.steps_event_data[stepIndex] as
                | Array<[string, string]>
                | undefined
            if (stepIndex > 0) {
                prevStepsEventData = experimentResult.baseline?.steps_event_data[stepIndex - 1] as
                    | Array<[string, string]>
                    | undefined
            }
        } else {
            const variantResult = experimentResult.variant_results?.find((v: any) => v.key === variantKey)
            stepsEventData = variantResult.steps_event_data[stepIndex] as Array<[string, string]> | undefined
            if (stepIndex > 0) {
                prevStepsEventData = variantResult.steps_event_data[stepIndex - 1] as
                    | Array<[string, string]>
                    | undefined
            }
        }
    }
    const handleClick = (): void => {
        setIsModalOpen(true)
    }

    return (
        <>
            <div
                className={clsx('StepBar')}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={
                    {
                        '--series-color': seriesColor,
                        '--conversion-rate': percentage(step.conversionRates.fromBasisStep, 1, true),
                    } as StepBarCSSProperties
                }
                ref={ref}
                onMouseEnter={() => {
                    if (ref.current) {
                        const rect = ref.current.getBoundingClientRect()
                        showTooltip([rect.x, rect.y, rect.width], stepIndex, step)
                    }
                }}
                onMouseLeave={() => hideTooltip()}
            >
                <div className="StepBar__backdrop" onClick={handleClick} style={{ cursor: 'pointer' }} />
                <div className="StepBar__fill" onClick={handleClick} style={{ cursor: 'pointer' }} />
            </div>

            {isModalOpen && stepsEventData && (
                <SampledSessionsModal
                    isOpen={isModalOpen}
                    onClose={() => setIsModalOpen(false)}
                    stepsEventData={stepsEventData}
                    prevStepsEventData={prevStepsEventData || []}
                    stepName={step.name}
                    variant={String(step.breakdown_value || 'control')}
                />
            )}
        </>
    )
}
