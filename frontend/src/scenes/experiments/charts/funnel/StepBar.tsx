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
    const [modalType, setModalType] = useState<'converted' | 'dropped'>('converted')

    const seriesColor = getSeriesColor(series)

    // Get sampled sessions from the experiment result
    // Find the variant result that matches this series
    let stepEventUUIDs: string[][] | undefined
    if (experimentResult) {
        const variantKey = series.breakdown_value
        if (variantKey === 'control') {
            stepEventUUIDs = experimentResult.baseline?.step_event_uuids
        } else {
            const variantResult = experimentResult.variant_results?.find((v: any) => v.key === variantKey)
            stepEventUUIDs = variantResult?.step_event_uuids
        }
    }
    const hasRecordings = stepEventUUIDs && stepEventUUIDs[stepIndex]?.length > 0

    const handleClick = (converted: boolean): void => {
        if (hasRecordings) {
            setModalType(converted ? 'converted' : 'dropped')
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
                    onClick={() => handleClick(false)}
                    style={{ cursor: hasRecordings ? 'pointer' : 'default' }}
                />
                <div
                    className="StepBar__fill"
                    onClick={() => handleClick(true)}
                    style={{ cursor: hasRecordings ? 'pointer' : 'default' }}
                />
            </div>

            {isModalOpen && stepEventUUIDs && (
                <SampledSessionsModal
                    isOpen={isModalOpen}
                    onClose={() => setIsModalOpen(false)}
                    title={`Step ${stepIndex + 1}: ${step.name}`}
                    sessions={stepEventUUIDs[stepIndex].map((id: string) => ({ session_id: id }))}
                    variant={String(series.breakdown_value || 'control')}
                    stepName={step.name}
                    converted={modalType === 'converted'}
                />
            )}
        </>
    )
}
