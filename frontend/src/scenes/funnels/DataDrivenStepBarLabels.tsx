import { useFunnelData } from './DataDrivenFunnel'

export function DataDrivenStepBarLabels(): JSX.Element {
    const { visibleStepsWithConversionMetrics } = useFunnelData()

    // For now, we'll show breakdown labels if they exist
    const hasBreakdowns = visibleStepsWithConversionMetrics[0]?.nested_breakdown?.length ?? 0 > 0

    if (!hasBreakdowns) {
        return <div className="StepBarLabels" />
    }

    return (
        <div className="StepBarLabels">
            {visibleStepsWithConversionMetrics[0].nested_breakdown?.map((breakdown, index) => (
                <div key={index} className="StepBarLabel">
                    <div 
                        className="StepBarLabel--color"
                        style={{
                            backgroundColor: `hsl(${(index * 137) % 360}, 70%, 50%)`,
                        }}
                    />
                    <span className="StepBarLabel--text">
                        {Array.isArray(breakdown.breakdown_value) 
                            ? breakdown.breakdown_value.join(', ') 
                            : breakdown.breakdown_value || 'Unknown'
                        }
                    </span>
                </div>
            ))}
        </div>
    )
}