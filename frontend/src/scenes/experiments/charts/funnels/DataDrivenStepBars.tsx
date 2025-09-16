import clsx from 'clsx'

import { FunnelStepWithConversionMetrics } from '~/types'

import { DataDrivenStepBar } from './DataDrivenStepBar'

interface DataDrivenStepBarsProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showPersonsModal: boolean
}

export function DataDrivenStepBars({ step, stepIndex, showPersonsModal }: DataDrivenStepBarsProps): JSX.Element {
    // For simplicity, we'll assume isOptional is always false
    const isOptional = false

    return (
        <div
            className={clsx('StepBars', stepIndex === 0 && 'StepBars--first')}
            style={{ opacity: isOptional ? 0.6 : 1 }}
        >
            <div className="StepBars__grid">
                {Array(5)
                    .fill(null)
                    .map((_, i) => (
                        <div
                            key={`gridline-${stepIndex}-${i}`}
                            className="StepBars__gridline StepBars__gridline--horizontal"
                        />
                    ))}
            </div>
            {step.nested_breakdown?.map((series) => (
                <DataDrivenStepBar
                    key={`bar-${stepIndex}-${series.order}`}
                    step={step}
                    stepIndex={stepIndex}
                    series={series}
                    showPersonsModal={showPersonsModal}
                />
            )) || (
                <DataDrivenStepBar
                    step={step}
                    stepIndex={stepIndex}
                    series={step}
                    showPersonsModal={showPersonsModal}
                />
            )}
        </div>
    )
}
