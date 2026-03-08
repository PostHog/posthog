import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import {
    DetectorConfig,
    DetectorType,
    MADDetectorConfig,
    PreprocessingConfig,
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
        value: DetectorType.MAD,
        label: 'MAD',
        description: 'Median absolute deviation (robust to outliers)',
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
            case DetectorType.MAD:
                onChange({ type: 'mad', threshold: 3.5, window: 30 } as MADDetectorConfig)
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
                    Detector type
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

            {value && <PreprocessingSection config={value} onChange={onChange} />}

            {value?.type === 'zscore' && <ZScoreConfig config={value as ZScoreDetectorConfig} onChange={onChange} />}
            {value?.type === 'mad' && <MADConfig config={value as MADDetectorConfig} onChange={onChange} />}
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

function MADConfig({
    config,
    onChange,
}: {
    config: MADDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Threshold (modified z-score)
                </label>
                <LemonInput
                    type="number"
                    min={1}
                    max={10}
                    step={0.5}
                    value={config.threshold ?? 3.5}
                    onChange={(val) => onChange({ ...config, threshold: val ? parseFloat(String(val)) : 3.5 })}
                    fullWidth
                />
                <p className="text-xs text-muted mt-1">
                    Like z-score but uses median instead of mean, making it robust to outliers. Higher = fewer alerts.
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
                    value={config.upper_bound ?? undefined}
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
                    value={config.lower_bound ?? undefined}
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

function PreprocessingSection({
    config,
    onChange,
}: {
    config: DetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    const preprocessing = config.preprocessing ?? {}
    const hasPreprocessing = (preprocessing.diffs_n ?? 0) > 0 || (preprocessing.smooth_n ?? 0) > 0

    const updatePreprocessing = (updates: Partial<PreprocessingConfig>): void => {
        const newPreprocessing = { ...preprocessing, ...updates }
        const isEmpty = !newPreprocessing.diffs_n && !newPreprocessing.smooth_n && !newPreprocessing.lags_n
        onChange({ ...config, preprocessing: isEmpty ? undefined : newPreprocessing })
    }

    return (
        <LemonCollapse
            panels={[
                {
                    key: 'preprocessing',
                    header: (
                        <span>
                            Preprocessing{' '}
                            {hasPreprocessing && (
                                <span className="text-xs text-muted ml-1">
                                    {[
                                        preprocessing.diffs_n ? 'differencing' : null,
                                        (preprocessing.smooth_n ?? 0) > 0
                                            ? `smoothing (${preprocessing.smooth_n})`
                                            : null,
                                    ]
                                        .filter(Boolean)
                                        .join(', ')}
                                </span>
                            )}
                        </span>
                    ),
                    content: (
                        <div className="space-y-3">
                            <div>
                                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                                    Differencing
                                </label>
                                <LemonSelect
                                    value={preprocessing.diffs_n ?? 0}
                                    onChange={(val) => updatePreprocessing({ diffs_n: val || undefined })}
                                    options={[
                                        { value: 0, label: 'None (raw values)' },
                                        { value: 1, label: 'First-order (Δ values)' },
                                    ]}
                                    fullWidth
                                />
                                <p className="text-xs text-muted mt-1">
                                    Differencing removes trends by using changes between consecutive values.
                                </p>
                            </div>
                            <div>
                                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                                    Smoothing window
                                </label>
                                <LemonInput
                                    type="number"
                                    min={0}
                                    max={30}
                                    step={1}
                                    value={preprocessing.smooth_n ?? 0}
                                    onChange={(val) =>
                                        updatePreprocessing({
                                            smooth_n: val ? parseInt(String(val), 10) : undefined,
                                        })
                                    }
                                    fullWidth
                                />
                                <p className="text-xs text-muted mt-1">
                                    Moving average over n data points. Reduces noise before detection. 0 = no smoothing.
                                </p>
                            </div>
                        </div>
                    ),
                },
            ]}
            size="small"
            embedded
        />
    )
}
