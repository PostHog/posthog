import { useMemo } from 'react'
import { humanFriendlyNumber } from 'lib/utils'

import { FunnelStepWithConversionMetrics } from '~/types'

import { useFunnelData } from './DataDrivenFunnel'

interface DataDrivenStepBarsProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showPersonsModal: boolean
}

export function DataDrivenStepBars({ 
    step, 
    stepIndex, 
    showPersonsModal 
}: DataDrivenStepBarsProps): JSX.Element {
    const { visibleStepsWithConversionMetrics } = useFunnelData()

    // Calculate the maximum count for scaling
    const maxCount = useMemo(() => {
        return Math.max(...visibleStepsWithConversionMetrics.map(s => s.count))
    }, [visibleStepsWithConversionMetrics])

    // If there are nested breakdowns, render bars for each breakdown
    if (step.nested_breakdown && step.nested_breakdown.length > 0) {
        return (
            <div className="StepBars">
                {step.nested_breakdown.map((breakdown, breakdownIndex) => (
                    <div key={breakdownIndex} className="StepBar">
                        <div 
                            className="StepBar--inner"
                            style={{
                                height: `${(breakdown.count / maxCount) * 100}%`,
                                backgroundColor: `hsl(${(breakdownIndex * 137) % 360}, 70%, 50%)`,
                            }}
                            title={`${breakdown.name}: ${humanFriendlyNumber(breakdown.count)}`}
                        />
                    </div>
                ))}
            </div>
        )
    }

    // Single bar for step without breakdowns
    return (
        <div className="StepBars">
            <div className="StepBar">
                <div 
                    className="StepBar--inner"
                    style={{
                        height: `${(step.count / maxCount) * 100}%`,
                        backgroundColor: `hsl(${(stepIndex * 137) % 360}, 70%, 50%)`,
                    }}
                    title={`${step.name}: ${humanFriendlyNumber(step.count)}`}
                />
            </div>
        </div>
    )
}