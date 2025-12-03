import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { DetectorDirection, DetectorType, ZScoreDetectorConfig } from '~/queries/schema/schema-general'

export interface ZScoreDetectorFormProps {
    config: ZScoreDetectorConfig
    onChange: (config: ZScoreDetectorConfig) => void
}

export function ZScoreDetectorForm({ config, onChange }: ZScoreDetectorFormProps): JSX.Element {
    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium w-32">Lookback periods:</span>
                <LemonInput
                    type="number"
                    value={config.lookback_periods}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            lookback_periods: Number(value) || 30,
                        })
                    }
                    min={3}
                    max={100}
                    size="small"
                    className="w-24"
                />
                <span className="text-xs text-muted">periods to calculate mean/std</span>
            </div>

            <div className="flex items-center gap-2">
                <span className="text-sm font-medium w-32">Z-score threshold:</span>
                <LemonInput
                    type="number"
                    value={config.z_threshold}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            z_threshold: Number(value) || 2.0,
                        })
                    }
                    min={0.5}
                    max={5}
                    step={0.1}
                    size="small"
                    className="w-24"
                />
                <span className="text-xs text-muted">standard deviations</span>
            </div>

            <div className="flex items-center gap-2">
                <span className="text-sm font-medium w-32">Direction:</span>
                <LemonSelect
                    value={config.direction}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            direction: value as DetectorDirection,
                        })
                    }
                    options={[
                        { value: DetectorDirection.BOTH, label: 'Both (above or below)' },
                        { value: DetectorDirection.ABOVE, label: 'Above only' },
                        { value: DetectorDirection.BELOW, label: 'Below only' },
                    ]}
                    size="small"
                />
            </div>

            <div className="text-xs text-muted bg-bg-light p-2 rounded">
                Triggers when the value is more than {config.z_threshold} standard deviations from the rolling mean
                calculated over the last {config.lookback_periods} periods.
            </div>
        </div>
    )
}

export function createDefaultZScoreConfig(): ZScoreDetectorConfig {
    return {
        type: DetectorType.ZSCORE,
        lookback_periods: 30,
        z_threshold: 2.0,
        direction: DetectorDirection.BOTH,
    }
}
