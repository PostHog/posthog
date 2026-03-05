import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import {
    DetectorConfig,
    DetectorType,
    ThresholdDetectorConfig,
    ZScoreDetectorConfig,
} from '~/queries/schema/schema-general'

interface DetectorSelectorProps {
    value: DetectorConfig | null
    onChange: (config: DetectorConfig | null) => void
}

const DETECTOR_OPTIONS = [
    {
        value: DetectorType.ZSCORE,
        label: 'Z-Score',
        description: 'Standard deviations from rolling mean',
    },
    {
        value: DetectorType.THRESHOLD,
        label: 'Threshold',
        description: 'Simple upper/lower bounds',
    },
]

export function DetectorSelector({ value, onChange }: DetectorSelectorProps): JSX.Element {
    const detectorType = value?.type || null

    const handleTypeChange = (type: string | null): void => {
        if (!type) {
            onChange(null)
            return
        }

        switch (type) {
            case DetectorType.ZSCORE:
                onChange({ type: 'zscore', threshold: 3.0, window: 30 } as ZScoreDetectorConfig)
                break
            case DetectorType.THRESHOLD:
                onChange({ type: 'threshold' } as ThresholdDetectorConfig)
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

            {value?.type === 'zscore' && <ZScoreConfig config={value as ZScoreDetectorConfig} onChange={onChange} />}
            {value?.type === 'threshold' && (
                <ThresholdConfig config={value as ThresholdDetectorConfig} onChange={onChange} />
            )}
        </div>
    )
}

function ZScoreConfig({
    config,
    onChange,
}: {
    config: ZScoreDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
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
                    onChange={(val) => onChange({ ...config, threshold: val ? parseFloat(String(val)) : 3.0 })}
                    fullWidth
                />
                <p className="text-xs text-muted mt-1">
                    Points more than this many standard deviations from the mean are flagged. Higher = fewer alerts.
                </p>
            </div>
            <WindowSizeInput config={config} onChange={onChange} />
        </div>
    )
}

function ThresholdConfig({
    config,
    onChange,
}: {
    config: ThresholdDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Upper bound
                </label>
                <LemonInput
                    type="number"
                    value={config.upper_bound ?? ''}
                    onChange={(val) => onChange({ ...config, upper_bound: val ? parseFloat(String(val)) : undefined })}
                    placeholder="No upper limit"
                    fullWidth
                />
            </div>
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Lower bound
                </label>
                <LemonInput
                    type="number"
                    value={config.lower_bound ?? ''}
                    onChange={(val) => onChange({ ...config, lower_bound: val ? parseFloat(String(val)) : undefined })}
                    placeholder="No lower limit"
                    fullWidth
                />
            </div>
            <p className="text-xs text-muted">Values outside these bounds are flagged as anomalies.</p>
        </div>
    )
}

function WindowSizeInput({
    config,
    onChange,
}: {
    config: { window?: number }
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
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
                    onChange({ ...config, window: val ? parseInt(String(val), 10) : 30 } as DetectorConfig)
                }
                fullWidth
            />
            <p className="text-xs text-muted mt-1">Number of historical data points for baseline calculation.</p>
        </div>
    )
}
