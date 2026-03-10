import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

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
        tooltip: 'Flags points that are unusually far from the rolling average. Good general-purpose detector.',
    },
    {
        value: DetectorType.MAD,
        label: 'MAD',
        tooltip:
            'Like Z-Score but uses the median instead of the mean, making it robust to existing outliers in your data.',
    },
]

function Label({ text, tooltip }: { text: string; tooltip: string }): JSX.Element {
    return (
        <label className="text-xs font-semibold text-secondary mb-1 flex items-center gap-1">
            {text}
            <Tooltip title={tooltip}>
                <IconInfo className="text-muted text-base" />
            </Tooltip>
        </label>
    )
}

export function DetectorSelector({ value, onChange }: DetectorSelectorProps): JSX.Element {
    const detectorType = value?.type || null

    const handleTypeChange = (type: string | null): void => {
        if (!type) {
            onChange(null)
            return
        }

        switch (type) {
            case DetectorType.ZSCORE:
                onChange({ type: 'zscore', threshold: 0.9, window: 30 } as ZScoreDetectorConfig)
                break
            case DetectorType.MAD:
                onChange({ type: 'mad', threshold: 0.9, window: 30 } as MADDetectorConfig)
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
                <Label text="Detector type" tooltip="The statistical method used to identify anomalies in your data." />
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
        <div className="grid grid-cols-2 gap-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? 0.9}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Points scoring above this are flagged. Higher = fewer alerts."
            />
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
        <div className="grid grid-cols-2 gap-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? 0.9}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Like Z-Score but uses median, making it robust to outliers. Higher = fewer alerts."
            />
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
        <div className="grid grid-cols-2 gap-3 pl-4 border-l-2 border-border">
            <div>
                <Label text="Upper bound" tooltip="Values above this are flagged. Leave empty for no upper limit." />
                <LemonInput
                    type="number"
                    value={config.upper_bound ?? undefined}
                    onChange={(val) => onChange({ ...config, upper_bound: val ? parseFloat(String(val)) : undefined })}
                    placeholder="No upper limit"
                />
            </div>
            <div>
                <Label text="Lower bound" tooltip="Values below this are flagged. Leave empty for no lower limit." />
                <LemonInput
                    type="number"
                    value={config.lower_bound ?? undefined}
                    onChange={(val) => onChange({ ...config, lower_bound: val ? parseFloat(String(val)) : undefined })}
                    placeholder="No lower limit"
                />
            </div>
        </div>
    )
}

function SensitivityInput({
    value,
    onChange,
    tooltip,
}: {
    value: number
    onChange: (value: number) => void
    tooltip: string
}): JSX.Element {
    return (
        <div>
            <Label text="Sensitivity" tooltip={tooltip} />
            <LemonInput
                type="number"
                min={0.5}
                max={0.99}
                step={0.05}
                value={value}
                onChange={(val) => onChange(val ? parseFloat(String(val)) : 0.9)}
            />
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
            <Label
                text="Window size"
                tooltip="Number of historical data points used to calculate the baseline. Larger = more stable, smaller = more responsive."
            />
            <LemonInput
                type="number"
                min={5}
                max={100}
                step={5}
                value={config.window ?? 30}
                onChange={(val) =>
                    onChange({ ...config, window: val ? parseInt(String(val), 10) : 30 } as DetectorConfig)
                }
            />
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
                        <div className="grid grid-cols-2 gap-3">
                            <div>
                                <Label
                                    text="Differencing"
                                    tooltip="Removes trends by using changes between consecutive values instead of raw values."
                                />
                                <LemonSelect
                                    value={preprocessing.diffs_n ?? 0}
                                    onChange={(val) => updatePreprocessing({ diffs_n: val || undefined })}
                                    options={[
                                        { value: 0, label: 'None (raw values)' },
                                        { value: 1, label: 'First-order (delta values)' },
                                    ]}
                                    fullWidth
                                />
                            </div>
                            <div>
                                <Label
                                    text="Smoothing"
                                    tooltip="Moving average over n data points. Reduces noise before detection. 0 = no smoothing."
                                />
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
                                />
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
