import clsx from 'clsx'

import { FunnelStepWithConversionMetrics } from '~/types'

import { DataDrivenStepBar } from './StepBar'

interface DataDrivenStepBarsProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
}

export function DataDrivenStepBars({ step, stepIndex }: DataDrivenStepBarsProps): JSX.Element {
    return (
        <div className={clsx('StepBars', stepIndex === 0 && 'StepBars--first')}>
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
                />
            )) || <DataDrivenStepBar step={step} stepIndex={stepIndex} series={step} />}
        </div>
    )
}
