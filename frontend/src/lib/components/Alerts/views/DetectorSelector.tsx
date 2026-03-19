import { IconInfo, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import {
    DetectorConfig,
    EnsembleDetectorConfig,
    EnsembleOperator,
    MADDetectorConfig,
    PreprocessingConfig,
    SingleDetectorConfig,
    ZScoreDetectorConfig,
} from '~/queries/schema/schema-general'

interface DetectorSelectorProps {
    value: DetectorConfig | null
    onChange: (config: DetectorConfig | null) => void
}

const DETECTOR_OPTIONS: Array<{ value: string; label: string; tooltip: string }> = [
    {
        value: 'zscore',
        label: 'Z-Score',
        tooltip: 'Flags points that are unusually far from the rolling average. Good general-purpose detector.',
    },
    {
        value: 'mad',
        label: 'MAD',
        tooltip:
            'Like Z-Score but uses the median instead of the mean, making it robust to existing outliers in your data.',
    },
    {
        value: 'ensemble',
        label: 'Ensemble',
        tooltip: 'Combine multiple detectors with AND/OR logic for more precise anomaly detection.',
    },
]

const SINGLE_DETECTOR_OPTIONS = DETECTOR_OPTIONS.filter((o) => o.value !== 'ensemble')

const DEFAULT_SINGLE_CONFIGS: Record<string, SingleDetectorConfig> = {
    zscore: { type: 'zscore', threshold: 0.9, window: 30 },
    mad: { type: 'mad', threshold: 0.9, window: 30 },
}

const DEFAULT_ENSEMBLE: EnsembleDetectorConfig = {
    type: 'ensemble',
    operator: EnsembleOperator.AND,
    detectors: [
        { type: 'zscore', threshold: 0.9, window: 30 },
        { type: 'mad', threshold: 0.9, window: 30 },
    ],
}

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

function getSelectedType(value: DetectorConfig | null): string {
    if (!value) {
        return 'zscore'
    }
    return value.type
}

export function DetectorSelector({ value, onChange }: DetectorSelectorProps): JSX.Element {
    const selectedType = getSelectedType(value)

    const handleTypeChange = (type: string): void => {
        if (type === 'ensemble') {
            onChange(DEFAULT_ENSEMBLE)
        } else {
            const existing = value?.type === type ? value : DEFAULT_SINGLE_CONFIGS[type]
            onChange(existing ?? DEFAULT_SINGLE_CONFIGS.zscore)
        }
    }

    return (
        <div className="space-y-4">
            <div>
                <Label text="Detector" tooltip="Statistical method used to identify anomalies in your data." />
                <LemonSelect
                    value={selectedType}
                    onChange={handleTypeChange}
                    options={DETECTOR_OPTIONS.map((o) => ({
                        value: o.value,
                        label: o.label,
                        tooltip: o.tooltip,
                    }))}
                    fullWidth
                />
            </div>

            {selectedType === 'ensemble' && value?.type === 'ensemble' ? (
                <EnsembleConfig config={value as EnsembleDetectorConfig} onChange={onChange} />
            ) : value && value.type !== 'ensemble' ? (
                <SingleDetectorConfigSection
                    config={value as SingleDetectorConfig}
                    onChange={(updated) => onChange(updated)}
                />
            ) : null}
        </div>
    )
}

function EnsembleConfig({
    config,
    onChange,
}: {
    config: EnsembleDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    const { operator, detectors } = config

    const handleOperatorChange = (newOperator: string): void => {
        onChange({ ...config, operator: newOperator as EnsembleOperator })
    }

    const handleDetectorChange = (index: number, updated: SingleDetectorConfig): void => {
        const newDetectors = [...detectors]
        newDetectors[index] = updated
        onChange({ ...config, detectors: newDetectors })
    }

    const handleDetectorTypeChange = (index: number, type: string): void => {
        const newDetectors = [...detectors]
        newDetectors[index] = DEFAULT_SINGLE_CONFIGS[type] ?? DEFAULT_SINGLE_CONFIGS.zscore
        onChange({ ...config, detectors: newDetectors })
    }

    const handleAddDetector = (): void => {
        const usedTypes = new Set(detectors.map((d) => d.type))
        const nextType =
            SINGLE_DETECTOR_OPTIONS.find((o) => !usedTypes.has(o.value as SingleDetectorConfig['type']))?.value ??
            'zscore'
        onChange({ ...config, detectors: [...detectors, DEFAULT_SINGLE_CONFIGS[nextType]] })
    }

    const handleRemoveDetector = (index: number): void => {
        if (detectors.length <= 2) {
            return
        }
        const newDetectors = detectors.filter((_, i) => i !== index)
        onChange({ ...config, detectors: newDetectors })
    }

    return (
        <div className="space-y-4">
            <div>
                <Label
                    text="Combine with"
                    tooltip="AND = all detectors must flag a point. OR = any detector flagging is enough."
                />
                <LemonSegmentedButton
                    value={operator}
                    onChange={handleOperatorChange}
                    options={[
                        {
                            value: EnsembleOperator.AND,
                            label: 'AND',
                            tooltip: 'Alert only when all detectors agree',
                        },
                        { value: EnsembleOperator.OR, label: 'OR', tooltip: 'Alert when any detector flags' },
                    ]}
                    size="small"
                />
            </div>

            {detectors.map((detector, index) => (
                <div key={index} className="border rounded p-3 space-y-3">
                    <div className="flex items-center gap-2">
                        <LemonSelect
                            value={detector.type}
                            onChange={(type) => handleDetectorTypeChange(index, type)}
                            options={SINGLE_DETECTOR_OPTIONS.map((o) => ({
                                value: o.value,
                                label: o.label,
                                tooltip: o.tooltip,
                            }))}
                            size="small"
                            className="flex-1"
                        />
                        {detectors.length > 2 && (
                            <LemonButton
                                icon={<IconX />}
                                size="small"
                                status="danger"
                                onClick={() => handleRemoveDetector(index)}
                                tooltip="Remove detector"
                            />
                        )}
                    </div>
                    <SingleDetectorConfigSection
                        config={detector}
                        onChange={(updated) => handleDetectorChange(index, updated)}
                    />
                </div>
            ))}

            <LemonButton type="secondary" icon={<IconPlus />} size="small" onClick={handleAddDetector}>
                Add detector
            </LemonButton>
        </div>
    )
}

function SingleDetectorConfigSection({
    config,
    onChange,
}: {
    config: SingleDetectorConfig
    onChange: (config: SingleDetectorConfig) => void
}): JSX.Element {
    return (
        <div>
            {(config.type === 'zscore' || config.type === 'mad') && (
                <div className="grid grid-cols-2 gap-3">
                    <SensitivityInput
                        value={(config as ZScoreDetectorConfig | MADDetectorConfig).threshold ?? 0.9}
                        onChange={(val) => onChange({ ...config, threshold: val } as SingleDetectorConfig)}
                        tooltip={
                            config.type === 'zscore'
                                ? 'Anomaly probability threshold (0-1). Points scoring above this are flagged. Higher = fewer alerts.'
                                : 'Anomaly probability threshold (0-1). Like Z-Score but uses median, making it robust to outliers. Higher = fewer alerts.'
                        }
                    />
                    <WindowSizeInput
                        config={config as ZScoreDetectorConfig | MADDetectorConfig}
                        onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    />
                </div>
            )}
            <PreprocessingSection config={config} onChange={(updated) => onChange(updated as SingleDetectorConfig)} />
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
    onChange: (config: SingleDetectorConfig) => void
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
                    onChange({ ...config, window: val ? parseInt(String(val), 10) : 30 } as SingleDetectorConfig)
                }
            />
        </div>
    )
}

function PreprocessingSection({
    config,
    onChange,
}: {
    config: SingleDetectorConfig
    onChange: (config: SingleDetectorConfig) => void
}): JSX.Element {
    const preprocessing = config.preprocessing ?? {}
    const hasPreprocessing = (preprocessing.diffs_n ?? 0) > 0 || (preprocessing.smooth_n ?? 0) > 0

    const updatePreprocessing = (updates: Partial<PreprocessingConfig>): void => {
        const newPreprocessing = { ...preprocessing, ...updates }
        const isEmpty =
            newPreprocessing.diffs_n == null && newPreprocessing.smooth_n == null && newPreprocessing.lags_n == null
        onChange({ ...config, preprocessing: isEmpty ? undefined : newPreprocessing } as SingleDetectorConfig)
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
