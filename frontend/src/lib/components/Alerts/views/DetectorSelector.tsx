import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonSelect, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

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

const DETECTOR_INFO: Record<string, { label: string; tooltip: string }> = {
    zscore: {
        label: 'Z-Score',
        tooltip: 'Flags points that are unusually far from the rolling average. Good general-purpose detector.',
    },
    mad: {
        label: 'MAD',
        tooltip:
            'Like Z-Score but uses the median instead of the mean, making it robust to existing outliers in your data.',
    },
}

const DEFAULT_CONFIGS: Record<string, SingleDetectorConfig> = {
    zscore: { type: 'zscore', threshold: 0.9, window: 30 },
    mad: { type: 'mad', threshold: 0.9, window: 30 },
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

/** Extract active single detector configs from the current value */
function getActiveDetectors(value: DetectorConfig | null): SingleDetectorConfig[] {
    if (!value) {
        return []
    }
    if (value.type === 'ensemble') {
        return (value as EnsembleDetectorConfig).detectors
    }
    return [value as SingleDetectorConfig]
}

/** Get the ensemble operator, defaulting to AND */
function getOperator(value: DetectorConfig | null): EnsembleOperator {
    if (value?.type === 'ensemble') {
        return (value as EnsembleDetectorConfig).operator
    }
    return EnsembleOperator.AND
}

/** Build the appropriate config from active detectors + operator */
function buildConfig(detectors: SingleDetectorConfig[], operator: EnsembleOperator): DetectorConfig | null {
    if (detectors.length === 0) {
        return null
    }
    if (detectors.length === 1) {
        return detectors[0]
    }
    return { type: 'ensemble', operator, detectors } as EnsembleDetectorConfig
}

export function DetectorSelector({ value, onChange }: DetectorSelectorProps): JSX.Element {
    const activeDetectors = getActiveDetectors(value)
    const operator = getOperator(value)
    const activeTypes = new Set(activeDetectors.map((d) => d.type))

    const handleToggle = (type: string, enabled: boolean): void => {
        let newDetectors: SingleDetectorConfig[]
        if (enabled) {
            const existing = activeDetectors.find((d) => d.type === type)
            newDetectors = [...activeDetectors, existing ?? DEFAULT_CONFIGS[type]]
        } else {
            newDetectors = activeDetectors.filter((d) => d.type !== type)
        }
        onChange(buildConfig(newDetectors, operator))
    }

    const handleOperatorChange = (newOperator: string): void => {
        onChange(buildConfig(activeDetectors, newOperator as EnsembleOperator))
    }

    const handleDetectorChange = (updated: SingleDetectorConfig): void => {
        const newDetectors = activeDetectors.map((d) => (d.type === updated.type ? updated : d))
        onChange(buildConfig(newDetectors, operator))
    }

    return (
        <div className="space-y-4">
            <div>
                <Label
                    text="Detectors"
                    tooltip="Select one or more statistical methods. Multiple detectors can be combined with AND/OR logic."
                />
                <div className="flex gap-4 mt-1">
                    {Object.entries(DETECTOR_INFO).map(([type, info]) => (
                        <Tooltip key={type} title={info.tooltip}>
                            <LemonCheckbox
                                label={info.label}
                                checked={activeTypes.has(type as SingleDetectorConfig['type'])}
                                onChange={(checked) => handleToggle(type, checked)}
                            />
                        </Tooltip>
                    ))}
                </div>
            </div>

            {activeDetectors.length > 1 && (
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
            )}

            {activeDetectors.map((detector) => (
                <DetectorConfigSection key={detector.type} config={detector} onChange={handleDetectorChange} />
            ))}
        </div>
    )
}

function DetectorConfigSection({
    config,
    onChange,
}: {
    config: SingleDetectorConfig
    onChange: (config: SingleDetectorConfig) => void
}): JSX.Element {
    const info = DETECTOR_INFO[config.type]
    const label = info?.label ?? config.type

    return (
        <div>
            <div className="text-xs font-semibold text-secondary mb-2">{label}</div>
            {(config.type === 'zscore' || config.type === 'mad') && (
                <div className="grid grid-cols-2 gap-3 pl-4 border-l-2 border-border">
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
        const isEmpty = !newPreprocessing.diffs_n && !newPreprocessing.smooth_n && !newPreprocessing.lags_n
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
