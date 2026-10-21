import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { FeatureImportanceChart } from './FeatureImportanceChart'
import { MetricCard } from './MetricCard'

/** The champion model: its metrics, feature drivers, and the agent's description. Renders nothing before a champion exists. */
export function LiveModelCard(): JSX.Element | null {
    const { champion } = useValues(autoresearchPipelineLogic)
    if (!champion) {
        return null
    }
    return (
        <div className="border rounded p-4 space-y-4">
            <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-muted">Live model</span>
                {champion.is_preliminary && (
                    <Tooltip title="Promoted on holdout AUC alone. Realized metrics confirm it once prediction horizons elapse.">
                        <LemonTag type="warning">Preliminary</LemonTag>
                    </Tooltip>
                )}
            </div>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                <MetricCard
                    label="Holdout AUC"
                    value={champion.holdout_score?.toFixed(3) ?? '—'}
                    tooltip="Offline AUC of the champion model, measured on held-out training data. Higher is better."
                />
                <MetricCard
                    label="Realized AUC"
                    value={champion.realized_score?.toFixed(3) ?? '—'}
                    tooltip="AUC of the champion model measured against actual outcomes once predictions matured. Higher is better."
                />
                <MetricCard
                    label="Calibration error"
                    value={champion.calibration_error?.toFixed(3) ?? '—'}
                    tooltip="Expected calibration error (ECE): how far predicted probabilities drift from observed rates. Lower is better."
                />
            </div>
            <FeatureImportanceChart explanation={champion.model_explanation} />
            {champion.agent_description && (
                <div className="text-sm text-muted italic">"{champion.agent_description}"</div>
            )}
        </div>
    )
}
