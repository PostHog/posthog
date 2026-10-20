import { useValues } from 'kea'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { FeatureImportanceChart } from './FeatureImportanceChart'
import { MetricCard } from './MetricCard'
import { SectionCard } from './SectionCard'

/** What drives the live model's predictions, and how well its probabilities match observed rates. Renders nothing before a champion exists. */
export function LiveModelDrivers(): JSX.Element | null {
    const { champion } = useValues(autoresearchPipelineLogic)
    if (!champion) {
        return null
    }
    return (
        <SectionCard title="What drives the live model">
            {champion.calibration_error != null && (
                <div className="max-w-xs">
                    <MetricCard
                        label="Calibration error"
                        value={champion.calibration_error.toFixed(3)}
                        tooltip="Expected calibration error (ECE): how far predicted probabilities drift from observed rates. Lower is better."
                    />
                </div>
            )}
            <FeatureImportanceChart explanation={champion.model_explanation} />
        </SectionCard>
    )
}
