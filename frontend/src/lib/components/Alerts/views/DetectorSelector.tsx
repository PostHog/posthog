import { IconInfo, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import {
    COPODDetectorConfig,
    DetectorConfig,
    DetectorType,
    ECODDetectorConfig,
    EnsembleDetectorConfig,
    EnsembleOperator,
    IQRDetectorConfig,
    IsolationForestDetectorConfig,
    KNNDetectorConfig,
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
        value: DetectorType.IQR,
        label: 'IQR',
        description: 'Interquartile range - classic box plot method',
    },
    {
        value: DetectorType.THRESHOLD,
        label: 'Threshold',
        description: 'Simple upper/lower bounds',
    },
    {
        value: 'ensemble',
        label: 'Ensemble',
        tooltip: 'Combine multiple detectors with AND/OR logic for more precise anomaly detection.',
    },
    {
        value: DetectorType.ECOD,
        label: 'ECOD',
        description: 'Empirical cumulative distribution',
    },
    {
        value: DetectorType.COPOD,
        label: 'COPOD',
        description: 'Copula-based outlier detection',
    },
    {
        value: DetectorType.ISOLATION_FOREST,
        label: 'Isolation Forest',
        description: 'Tree-based anomaly isolation',
    },
    {
        value: DetectorType.KNN,
        label: 'KNN',
        description: 'K-nearest neighbors distance',
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

    const handleTypeChange = (type: string | null): void => {
        if (!type) {
            onChange(null)
            return
        }

        if (type === 'ensemble') {
            onChange(DEFAULT_ENSEMBLE)
            return
        }

        switch (type) {
            case DetectorType.ZSCORE:
                onChange({ type: 'zscore', threshold: 3.0, window: 30 } as ZScoreDetectorConfig)
                break
            case DetectorType.MAD:
                onChange({ type: 'mad', threshold: 3.5, window: 30 } as MADDetectorConfig)
                break
            case DetectorType.IQR:
                onChange({ type: 'iqr', multiplier: 1.5, window: 30 } as IQRDetectorConfig)
                break
            case DetectorType.THRESHOLD:
                onChange({ type: 'threshold' } as ThresholdDetectorConfig)
                break
            case DetectorType.ECOD:
                onChange({ type: 'ecod', contamination: 0.1 } as ECODDetectorConfig)
                break
            case DetectorType.COPOD:
                onChange({ type: 'copod', contamination: 0.1 } as COPODDetectorConfig)
                break
            case DetectorType.ISOLATION_FOREST:
                onChange({
                    type: 'isolation_forest',
                    contamination: 0.1,
                    n_estimators: 100,
                } as IsolationForestDetectorConfig)
                break
            case DetectorType.KNN:
                onChange({ type: 'knn', contamination: 0.1, n_neighbors: 5, method: 'largest' } as KNNDetectorConfig)
                break
            default:
                onChange(null)
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
            {config.type === 'iqr' && (
                <IQRConfig config={config as IQRDetectorConfig} onChange={(updated) => onChange(updated as SingleDetectorConfig)} />
            )}
            {config.type === 'ecod' && (
                <ECODConfig config={config as ECODDetectorConfig} onChange={(updated) => onChange(updated as SingleDetectorConfig)} />
            )}
            {config.type === 'copod' && (
                <COPODConfig config={config as COPODDetectorConfig} onChange={(updated) => onChange(updated as SingleDetectorConfig)} />
            )}
            {config.type === 'isolation_forest' && (
                <IsolationForestConfig config={config as IsolationForestDetectorConfig} onChange={(updated) => onChange(updated as SingleDetectorConfig)} />
            )}
            {config.type === 'knn' && (
                <KNNConfig config={config as KNNDetectorConfig} onChange={(updated) => onChange(updated as SingleDetectorConfig)} />
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

function IQRConfig({
    config,
    onChange,
}: {
    config: IQRDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    IQR multiplier
                </label>
                <LemonInput
                    type="number"
                    min={1}
                    max={5}
                    step={0.5}
                    value={config.multiplier ?? 1.5}
                    onChange={(val) => onChange({ ...config, multiplier: val ? parseFloat(String(val)) : 1.5 })}
                    fullWidth
                />
                <p className="text-xs text-muted mt-1">1.5 = mild outliers (standard), 3.0 = extreme outliers only.</p>
            </div>
            <WindowSizeInput config={config} onChange={onChange} />
        </div>
    )
}

function ECODConfig({
    config,
    onChange,
}: {
    config: ECODDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <ContaminationInput config={config} onChange={onChange} />
            <p className="text-xs text-muted">Empirical cumulative distribution - parameter-free and interpretable.</p>
        </div>
    )
}

function COPODConfig({
    config,
    onChange,
}: {
    config: COPODDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <ContaminationInput config={config} onChange={onChange} />
            <p className="text-xs text-muted">Copula-based detection - efficient and parameter-free.</p>
        </div>
    )
}

function IsolationForestConfig({
    config,
    onChange,
}: {
    config: IsolationForestDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <ContaminationInput config={config} onChange={onChange} />
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Number of trees
                </label>
                <LemonInput
                    type="number"
                    min={10}
                    max={500}
                    step={10}
                    value={config.n_estimators ?? 100}
                    onChange={(val) => onChange({ ...config, n_estimators: val ? parseInt(String(val), 10) : 100 })}
                    fullWidth
                />
            </div>
            <p className="text-xs text-muted">Isolates anomalies using random forest - good for complex patterns.</p>
        </div>
    )
}

function KNNConfig({
    config,
    onChange,
}: {
    config: KNNDetectorConfig
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <ContaminationInput config={config} onChange={onChange} />
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Number of neighbors
                </label>
                <LemonInput
                    type="number"
                    min={1}
                    max={50}
                    step={1}
                    value={config.n_neighbors ?? 5}
                    onChange={(val) => onChange({ ...config, n_neighbors: val ? parseInt(String(val), 10) : 5 })}
                    fullWidth
                />
            </div>
            <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                    Distance method
                </label>
                <LemonSelect
                    value={config.method ?? 'largest'}
                    onChange={(val) => onChange({ ...config, method: val as 'largest' | 'mean' | 'median' })}
                    options={[
                        { value: 'largest', label: 'Largest' },
                        { value: 'mean', label: 'Mean' },
                        { value: 'median', label: 'Median' },
                    ]}
                    fullWidth
                />
            </div>
            <p className="text-xs text-muted">
                Uses distance to nearest neighbors - points far from others are anomalies.
            </p>
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

function ContaminationInput({
    config,
    onChange,
}: {
    config: { contamination?: number }
    onChange: (config: DetectorConfig) => void
}): JSX.Element {
    return (
        <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-secondary mb-1 block">
                Expected outlier proportion
            </label>
            <LemonInput
                type="number"
                min={0.01}
                max={0.5}
                step={0.01}
                value={config.contamination ?? 0.1}
                onChange={(val) =>
                    onChange({ ...config, contamination: val ? parseFloat(String(val)) : 0.1 } as DetectorConfig)
                }
                fullWidth
            />
            <p className="text-xs text-muted mt-1">
                Fraction of data expected to be outliers (0.1 = 10%). Lower = stricter.
            </p>
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
