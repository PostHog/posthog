import './FunnelBarHorizontal/FunnelBarHorizontal.scss'

import { humanFriendlyNumber, percentage } from 'lib/utils'

import { ChartParams } from '~/types'

import { useFunnelData } from './DataDrivenFunnel'

export function DataDrivenFunnelBarHorizontal({ 
    showPersonsModal: showPersonsModalProp = true 
}: ChartParams): JSX.Element {
    const { visibleStepsWithConversionMetrics } = useFunnelData()
    const showPersonsModal = showPersonsModalProp

    if (!visibleStepsWithConversionMetrics.length) {
        return <div>No funnel data available</div>
    }

    const maxCount = Math.max(...visibleStepsWithConversionMetrics.map(step => step.count))

    return (
        <div className="FunnelBarHorizontal" data-attr="funnel-bar-horizontal">
            <div className="FunnelBarHorizontal--container">
                {visibleStepsWithConversionMetrics.map((step, stepIndex) => (
                    <div key={stepIndex} className="FunnelBarHorizontal--step">
                        <div className="FunnelBarHorizontal--step-header">
                            <span className="FunnelBarHorizontal--step-number">
                                {stepIndex + 1}
                            </span>
                            <span className="FunnelBarHorizontal--step-name">
                                {step.custom_name || step.name}
                            </span>
                        </div>

                        <div className="FunnelBarHorizontal--bar-container">
                            <div 
                                className="FunnelBarHorizontal--bar"
                                style={{
                                    width: `${(step.count / maxCount) * 100}%`,
                                    backgroundColor: `hsl(${(stepIndex * 137) % 360}, 70%, 50%)`,
                                }}
                            />
                            <div className="FunnelBarHorizontal--bar-labels">
                                <span className="FunnelBarHorizontal--count">
                                    {humanFriendlyNumber(step.count)} users
                                </span>
                                {stepIndex > 0 && (
                                    <span className="FunnelBarHorizontal--conversion">
                                        {percentage(step.conversionRates.fromPrevious, 1, true)} converted
                                    </span>
                                )}
                            </div>
                        </div>

                        {stepIndex > 0 && (
                            <div className="FunnelBarHorizontal--dropped">
                                <span>{humanFriendlyNumber(step.droppedOffFromPrevious)} dropped off</span>
                            </div>
                        )}

                        {step.average_conversion_time != null && (
                            <div className="FunnelBarHorizontal--time">
                                <span>
                                    Avg time: {step.average_conversion_time > 60
                                        ? `${Math.round(step.average_conversion_time / 60)}m`
                                        : `${Math.round(step.average_conversion_time)}s`
                                    }
                                </span>
                            </div>
                        )}

                        {/* Show breakdown bars if they exist */}
                        {step.nested_breakdown && step.nested_breakdown.length > 0 && (
                            <div className="FunnelBarHorizontal--breakdowns">
                                {step.nested_breakdown.map((breakdown, breakdownIndex) => (
                                    <div key={breakdownIndex} className="FunnelBarHorizontal--breakdown">
                                        <div 
                                            className="FunnelBarHorizontal--breakdown-bar"
                                            style={{
                                                width: `${(breakdown.count / maxCount) * 100}%`,
                                                backgroundColor: `hsl(${(breakdownIndex * 137) % 360}, 70%, 50%)`,
                                            }}
                                        />
                                        <span className="FunnelBarHorizontal--breakdown-label">
                                            {Array.isArray(breakdown.breakdown_value) 
                                                ? breakdown.breakdown_value.join(', ') 
                                                : breakdown.breakdown_value || 'Unknown'
                                            }: {humanFriendlyNumber(breakdown.count)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}