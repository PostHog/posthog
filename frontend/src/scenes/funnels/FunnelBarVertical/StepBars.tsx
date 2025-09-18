import clsx from 'clsx'
import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { funnelDataLogic } from '../funnelDataLogic'
import { StepBar, StepBarProps } from './StepBar'

export function StepBars({ step, stepIndex, showPersonsModal }: Omit<StepBarProps, 'series'>): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { isStepOptional } = useValues(funnelDataLogic(insightProps))

    const isOptional = isStepOptional(stepIndex + 1)
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
                <StepBar
                    key={`bar-${stepIndex}-${series.order}`}
                    step={step}
                    stepIndex={stepIndex}
                    series={series}
                    showPersonsModal={showPersonsModal}
                />
            ))}
        </div>
    )
}
