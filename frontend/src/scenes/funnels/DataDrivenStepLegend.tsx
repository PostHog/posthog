import { humanFriendlyNumber, percentage } from 'lib/utils'

import { FunnelStepWithConversionMetrics } from '~/types'

interface DataDrivenStepLegendProps {
    step: FunnelStepWithConversionMetrics
    stepIndex: number
    showTime: boolean
    showPersonsModal: boolean
}

export function DataDrivenStepLegend({ 
    step, 
    stepIndex, 
    showTime, 
    showPersonsModal 
}: DataDrivenStepLegendProps): JSX.Element {
    return (
        <div className="StepLegend">
            <div className="StepLegend--header">
                <span className="StepLegend--step-number">{stepIndex + 1}</span>
                <span className="StepLegend--step-name" title={step.name}>
                    {step.custom_name || step.name}
                </span>
            </div>
            
            <div className="StepLegend--count">
                <span className="StepLegend--count-value">
                    {humanFriendlyNumber(step.count)}
                </span>
                <span className="StepLegend--count-label">users</span>
            </div>

            {stepIndex > 0 && (
                <div className="StepLegend--conversion">
                    <span className="StepLegend--conversion-rate">
                        {percentage(step.conversionRates.fromPrevious, 1, true)}
                    </span>
                    <span className="StepLegend--conversion-label">converted</span>
                </div>
            )}

            {stepIndex > 0 && (
                <div className="StepLegend--dropped">
                    <span className="StepLegend--dropped-value">
                        {humanFriendlyNumber(step.droppedOffFromPrevious)}
                    </span>
                    <span className="StepLegend--dropped-label">dropped off</span>
                </div>
            )}

            {showTime && step.average_conversion_time != null && (
                <div className="StepLegend--time">
                    <span className="StepLegend--time-value">
                        {step.average_conversion_time > 60
                            ? `${Math.round(step.average_conversion_time / 60)}m`
                            : `${Math.round(step.average_conversion_time)}s`
                        }
                    </span>
                    <span className="StepLegend--time-label">avg time</span>
                </div>
            )}
        </div>
    )
}