import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { DetectorConfig, DetectorType, ZScoreDetectorConfig } from '~/queries/schema/schema-general'

interface DetectorSelectorProps {
    value: DetectorConfig | null
    onChange: (config: DetectorConfig | null) => void
}

const DETECTOR_OPTIONS = [
    {
        value: DetectorType.ZSCORE,
        label: 'Z-Score',
        description: 'Statistical anomaly detection using standard deviations from the mean',
    },
]

export function DetectorSelector({ value, onChange }: DetectorSelectorProps): JSX.Element {
    const detectorType = value?.type || null

    const handleTypeChange = (type: string | null): void => {
        if (!type) {
            onChange(null)
            return
        }

        // Create default config for the selected type
        switch (type) {
            case DetectorType.ZSCORE:
                onChange({
                    type: 'zscore',
                    threshold: 3.0,
                    window: 30,
                } as ZScoreDetectorConfig)
                break
            default:
                onChange(null)
        }
    }

    return (
        <div className="space-y-4">
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Detector Type
                </label>
                <LemonSelect
                    value={detectorType}
                    onChange={handleTypeChange}
                    options={DETECTOR_OPTIONS}
                    placeholder="Select a detector..."
                    allowClear
                    fullWidth
                />
            </div>

            {value?.type === 'zscore' && (
                <ZScoreConfig config={value as ZScoreDetectorConfig} onChange={(config) => onChange(config)} />
            )}
        </div>
    )
}

interface ZScoreConfigProps {
    config: ZScoreDetectorConfig
    onChange: (config: ZScoreDetectorConfig) => void
}

function ZScoreConfig({ config, onChange }: ZScoreConfigProps): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Threshold (standard deviations)
                </label>
                <LemonInput
                    type="number"
                    min={1}
                    max={10}
                    step={0.5}
                    value={config.threshold ?? 3.0}
                    onChange={(val) =>
                        onChange({
                            ...config,
                            threshold: val ? parseFloat(String(val)) : 3.0,
                        })
                    }
                    fullWidth
                />
                <p className="text-xs text-muted mt-1">
                    Points more than this many standard deviations from the mean are flagged as anomalies. Higher values
                    = fewer alerts.
                </p>
            </div>

            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Window size (data points)
                </label>
                <LemonInput
                    type="number"
                    min={5}
                    max={100}
                    step={5}
                    value={config.window ?? 30}
                    onChange={(val) =>
                        onChange({
                            ...config,
                            window: val ? parseInt(String(val), 10) : 30,
                        })
                    }
                    fullWidth
                />
                <p className="text-xs text-muted mt-1">
                    Number of historical data points used to calculate the mean and standard deviation.
                </p>
            </div>
        </div>
    )
}
