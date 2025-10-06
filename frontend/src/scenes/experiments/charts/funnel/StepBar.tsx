import clsx from 'clsx'
import { useActions } from 'kea'
import { useRef } from 'react'

import { getSeriesColor } from 'lib/colors'
import { percentage } from 'lib/utils'

import { SessionData } from '~/queries/schema/schema-general'
import { FunnelStepWithConversionMetrics } from '~/types'

import { useTooltip } from './FunnelBarVertical'
import { useFunnelChartData } from './FunnelChart'
import { sampledSessionsModalLogic } from './sampledSessionsModalLogic'

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
    const { openModal } = useActions(sampledSessionsModalLogic)

    const seriesColor = getSeriesColor((step as any).breakdown_index)

    // Get sampled sessions from the experiment result
    // Find the variant result that matches this series
    let sessionData: SessionData[] | undefined
    if (experimentResult) {
        const variantKey = step.breakdown_value
        if (variantKey === 'control') {
            sessionData = experimentResult.baseline.step_sessions?.[stepIndex]
        } else {
            const variantResult = experimentResult.variant_results?.find((v: any) => v.key === variantKey)
            sessionData = variantResult?.step_sessions?.[stepIndex] as SessionData[] | undefined
        }
    }
    const handleClick = (): void => {
        if (sessionData) {
            openModal({
                sessionData,
                stepName: step.name,
                variant: String(step.breakdown_value || 'control'),
            })
        }
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
                        showTooltip([rect.x, rect.y, rect.width], stepIndex, step, !!sessionData)
                    }
                }}
                onMouseLeave={() => hideTooltip()}
            >
                <div className="StepBar__backdrop" onClick={handleClick} style={{ cursor: 'pointer' }} />
                <div className="StepBar__fill" onClick={handleClick} style={{ cursor: 'pointer' }} />
            </div>
        </>
    )
}
