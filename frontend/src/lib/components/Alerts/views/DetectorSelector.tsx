import { LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import {
    DetectorConfig,
    DetectorType,
    EnsembleMode,
    InsightThresholdType,
    PreprocessingConfig,
    SingleDetectorConfig,
} from '~/queries/schema/schema-general'

const DETECTOR_OPTIONS: { value: DetectorType; label: string; description: string }[] = [
    { value: DetectorType.THRESHOLD, label: 'Threshold', description: 'Simple upper/lower bounds' },
    { value: DetectorType.ZSCORE, label: 'Z-Score', description: 'Statistical: standard deviations from mean' },
    { value: DetectorType.MAD, label: 'MAD', description: 'Statistical: median absolute deviation' },
    { value: DetectorType.IQR, label: 'IQR', description: 'Statistical: interquartile range' },
    {
        value: DetectorType.ISOLATION_FOREST,
        label: 'Isolation Forest',
        description: 'ML: tree-based anomaly detection',
    },
    { value: DetectorType.ECOD, label: 'ECOD', description: 'ML: empirical cumulative distribution' },
    { value: DetectorType.COPOD, label: 'COPOD', description: 'ML: copula-based outlier detection' },
    { value: DetectorType.KNN, label: 'KNN', description: 'ML: k-nearest neighbors distance' },
    { value: DetectorType.ENSEMBLE, label: 'Ensemble', description: 'Combine multiple detectors' },
]

interface DetectorParamsProps {
    config: DetectorConfig
    onChange: (config: DetectorConfig) => void
}

function FieldLabel({ children }: { children: React.ReactNode }): JSX.Element {
    return <label className="text-xs font-medium text-muted-alt">{children}</label>
}

function StatisticalParams({
    config,
    onChange,
    thresholdLabel = 'Threshold',
    defaultThreshold = 3.0,
}: DetectorParamsProps & { thresholdLabel?: string; defaultThreshold?: number }): JSX.Element {
    const singleConfig = config as SingleDetectorConfig
    const threshold = (singleConfig as any).threshold ?? defaultThreshold
    const window = (singleConfig as any).window ?? 30

    return (
        <div className="flex gap-4 items-end mt-2">
            <div>
                <FieldLabel>{thresholdLabel}</FieldLabel>
                <LemonInput
                    type="number"
                    className="w-20"
                    value={threshold}
                    onChange={(value) =>
                        onChange({ ...config, threshold: value ?? defaultThreshold } as DetectorConfig)
                    }
                    step={0.5}
                    min={0.5}
                />
            </div>
            <div>
                <FieldLabel>Window</FieldLabel>
                <LemonInput
                    type="number"
                    className="w-20"
                    value={window}
                    onChange={(value) => onChange({ ...config, window: value ?? 30 } as DetectorConfig)}
                    min={5}
                    max={100}
                />
            </div>
        </div>
    )
}

function ThresholdParams({ config, onChange }: DetectorParamsProps): JSX.Element {
    const singleConfig = config as {
        type: DetectorType.THRESHOLD
        threshold_type: InsightThresholdType
        bounds: { lower?: number; upper?: number }
    }
    const bounds = singleConfig.bounds ?? {}

    return (
        <div className="flex gap-4 items-center mt-2">
            <div>
                <FieldLabel>Less than</FieldLabel>
                <LemonInput
                    type="number"
                    className="w-24"
                    value={bounds.lower}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            bounds: { ...bounds, lower: value ?? undefined },
                        } as DetectorConfig)
                    }
                    placeholder="No min"
                />
            </div>
            <div>
                <FieldLabel>Or more than</FieldLabel>
                <LemonInput
                    type="number"
                    className="w-24"
                    value={bounds.upper}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            bounds: { ...bounds, upper: value ?? undefined },
                        } as DetectorConfig)
                    }
                    placeholder="No max"
                />
            </div>
        </div>
    )
}

function IQRParams({ config, onChange }: DetectorParamsProps): JSX.Element {
    const multiplier = (config as any).multiplier ?? 1.5
    const window = (config as any).window ?? 30

    return (
        <div className="flex gap-4 items-end mt-2">
            <div>
                <FieldLabel>Multiplier</FieldLabel>
                <LemonInput
                    type="number"
                    className="w-20"
                    value={multiplier}
                    onChange={(value) => onChange({ ...config, multiplier: value ?? 1.5 } as DetectorConfig)}
                    step={0.5}
                    min={0.5}
                />
            </div>
            <div>
                <FieldLabel>Window</FieldLabel>
                <LemonInput
                    type="number"
                    className="w-20"
                    value={window}
                    onChange={(value) => onChange({ ...config, window: value ?? 30 } as DetectorConfig)}
                    min={5}
                    max={100}
                />
            </div>
        </div>
    )
}

function PyODParams({
    config,
    onChange,
    showNeighbors = false,
}: DetectorParamsProps & { showNeighbors?: boolean }): JSX.Element {
    const contamination = (config as any).contamination ?? 0.1
    const nNeighbors = (config as any).n_neighbors ?? 5

    return (
        <div className="flex gap-4 items-end mt-2">
            <div>
                <FieldLabel>Contamination</FieldLabel>
                <LemonInput
                    type="number"
                    className="w-24"
                    value={contamination}
                    onChange={(value) => onChange({ ...config, contamination: value ?? 0.1 } as DetectorConfig)}
                    step={0.05}
                    min={0.01}
                    max={0.5}
                />
            </div>
            {showNeighbors && (
                <div>
                    <FieldLabel>Neighbors</FieldLabel>
                    <LemonInput
                        type="number"
                        className="w-20"
                        value={nNeighbors}
                        onChange={(value) => onChange({ ...config, n_neighbors: value ?? 5 } as DetectorConfig)}
                        min={1}
                        max={20}
                    />
                </div>
            )}
        </div>
    )
}

function PreprocessingEditor({
    preprocessing,
    onChange,
    showLags = false,
}: {
    preprocessing?: PreprocessingConfig
    onChange: (preprocessing: PreprocessingConfig | undefined) => void
    showLags?: boolean
}): JSX.Element {
    const config = preprocessing ?? { diffs: false }

    return (
        <div className="border rounded p-3 mt-2 bg-surface-primary-alt">
            <div className="text-sm font-semibold mb-2">Preprocessing</div>
            <div className="flex gap-4 items-end flex-wrap">
                <div>
                    <FieldLabel>First difference</FieldLabel>
                    <LemonSwitch
                        checked={config.diffs ?? false}
                        onChange={(checked) => onChange({ ...config, diffs: checked })}
                    />
                </div>
                <div>
                    <FieldLabel>Smoothing</FieldLabel>
                    <LemonInput
                        type="number"
                        className="w-20"
                        value={config.smoothing ?? 0}
                        onChange={(value) => onChange({ ...config, smoothing: value ?? 0 })}
                        min={0}
                        max={20}
                        placeholder="0"
                    />
                </div>
                {showLags && (
                    <div>
                        <FieldLabel>Lags</FieldLabel>
                        <LemonInput
                            type="number"
                            className="w-20"
                            value={config.lags ?? 0}
                            onChange={(value) => onChange({ ...config, lags: value ?? 0 })}
                            min={0}
                            max={10}
                            placeholder="0"
                        />
                    </div>
                )}
            </div>
        </div>
    )
}

function EnsembleEditor({ config, onChange }: DetectorParamsProps): JSX.Element {
    const ensembleConfig = config as {
        type: DetectorType.ENSEMBLE
        mode: EnsembleMode
        detectors: SingleDetectorConfig[]
    }
    const mode = ensembleConfig.mode ?? EnsembleMode.OR
    const detectors = ensembleConfig.detectors ?? []

    const addDetector = (): void => {
        if (detectors.length >= 5) {
            return
        }
        onChange({
            ...ensembleConfig,
            detectors: [
                ...detectors,
                { type: DetectorType.THRESHOLD, threshold_type: InsightThresholdType.ABSOLUTE, bounds: {} },
            ],
        } as unknown as DetectorConfig)
    }

    const removeDetector = (index: number): void => {
        onChange({
            ...ensembleConfig,
            detectors: detectors.filter((_, i) => i !== index),
        } as unknown as DetectorConfig)
    }

    const updateDetector = (index: number, newConfig: SingleDetectorConfig): void => {
        onChange({
            ...ensembleConfig,
            detectors: detectors.map((d, i) => (i === index ? newConfig : d)),
        } as unknown as DetectorConfig)
    }

    return (
        <div className="mt-2 space-y-3">
            <div className="flex gap-4 items-end">
                <div>
                    <FieldLabel>Mode</FieldLabel>
                    <LemonSelect
                        className="w-24"
                        value={mode}
                        options={[
                            { value: EnsembleMode.OR, label: 'OR' },
                            { value: EnsembleMode.AND, label: 'AND' },
                        ]}
                        onChange={(value) => onChange({ ...ensembleConfig, mode: value } as unknown as DetectorConfig)}
                    />
                </div>
                <div className="text-muted-alt text-sm">
                    {mode === EnsembleMode.OR ? 'Any detector triggers alert' : 'All detectors must trigger'}
                </div>
            </div>

            {detectors.map((detector, index) => (
                <div key={index} className="border rounded p-3 bg-surface-primary-alt">
                    <div className="flex justify-between items-center mb-2">
                        <span className="text-sm font-semibold">Detector {index + 1}</span>
                        {detectors.length > 2 && (
                            <button
                                className="text-danger text-sm hover:underline"
                                onClick={() => removeDetector(index)}
                            >
                                Remove
                            </button>
                        )}
                    </div>
                    <DetectorSelector
                        config={detector}
                        onChange={(newConfig) => updateDetector(index, newConfig as SingleDetectorConfig)}
                        excludeEnsemble
                    />
                </div>
            ))}

            {detectors.length < 5 && (
                <button className="text-link text-sm hover:underline" onClick={addDetector}>
                    + Add detector
                </button>
            )}
            {detectors.length < 2 && <div className="text-warning text-sm">Ensemble requires at least 2 detectors</div>}
        </div>
    )
}

interface DetectorSelectorProps {
    config: DetectorConfig | null | undefined
    onChange: (config: DetectorConfig) => void
    excludeEnsemble?: boolean
    showPreprocessing?: boolean
}

export function DetectorSelector({
    config,
    onChange,
    excludeEnsemble = false,
    showPreprocessing = true,
}: DetectorSelectorProps): JSX.Element {
    const currentType = config?.type ?? DetectorType.THRESHOLD
    const preprocessing = (config as any)?.preprocessing as PreprocessingConfig | undefined

    const options = excludeEnsemble
        ? DETECTOR_OPTIONS.filter((o) => o.value !== DetectorType.ENSEMBLE)
        : DETECTOR_OPTIONS

    const handleTypeChange = (newType: DetectorType): void => {
        // Create default config for new type
        let newConfig: DetectorConfig
        switch (newType) {
            case DetectorType.THRESHOLD:
                newConfig = { type: DetectorType.THRESHOLD, threshold_type: InsightThresholdType.ABSOLUTE, bounds: {} }
                break
            case DetectorType.ZSCORE:
                newConfig = { type: DetectorType.ZSCORE, threshold: 3.0, window: 30 }
                break
            case DetectorType.MAD:
                newConfig = { type: DetectorType.MAD, threshold: 3.0, window: 30 }
                break
            case DetectorType.IQR:
                newConfig = { type: DetectorType.IQR, multiplier: 1.5, window: 30 }
                break
            case DetectorType.ISOLATION_FOREST:
                newConfig = { type: DetectorType.ISOLATION_FOREST, contamination: 0.1 }
                break
            case DetectorType.ECOD:
                newConfig = { type: DetectorType.ECOD, contamination: 0.1 }
                break
            case DetectorType.COPOD:
                newConfig = { type: DetectorType.COPOD, contamination: 0.1 }
                break
            case DetectorType.KNN:
                newConfig = { type: DetectorType.KNN, contamination: 0.1, n_neighbors: 5 }
                break
            case DetectorType.ENSEMBLE:
                newConfig = {
                    type: DetectorType.ENSEMBLE,
                    mode: EnsembleMode.OR,
                    detectors: [
                        { type: DetectorType.THRESHOLD, threshold_type: InsightThresholdType.ABSOLUTE, bounds: {} },
                        { type: DetectorType.ZSCORE, threshold: 3.0, window: 30 },
                    ],
                } as unknown as DetectorConfig
                break
            default:
                newConfig = { type: DetectorType.THRESHOLD, threshold_type: InsightThresholdType.ABSOLUTE, bounds: {} }
        }
        onChange(newConfig)
    }

    const handlePreprocessingChange = (newPreprocessing: PreprocessingConfig | undefined): void => {
        onChange({ ...config, preprocessing: newPreprocessing } as DetectorConfig)
    }

    return (
        <div>
            <div>
                <FieldLabel>Detector type</FieldLabel>
                <LemonSelect
                    fullWidth
                    value={currentType}
                    options={options.map((o) => ({
                        value: o.value,
                        label: o.label,
                        tooltip: o.description,
                    }))}
                    onChange={handleTypeChange}
                />
            </div>

            {currentType === DetectorType.THRESHOLD && <ThresholdParams config={config!} onChange={onChange} />}
            {currentType === DetectorType.ZSCORE && (
                <StatisticalParams config={config!} onChange={onChange} thresholdLabel="Z-threshold" />
            )}
            {currentType === DetectorType.MAD && (
                <StatisticalParams config={config!} onChange={onChange} thresholdLabel="MAD threshold" />
            )}
            {currentType === DetectorType.IQR && <IQRParams config={config!} onChange={onChange} />}
            {currentType === DetectorType.ISOLATION_FOREST && <PyODParams config={config!} onChange={onChange} />}
            {currentType === DetectorType.ECOD && <PyODParams config={config!} onChange={onChange} />}
            {currentType === DetectorType.COPOD && <PyODParams config={config!} onChange={onChange} />}
            {currentType === DetectorType.KNN && <PyODParams config={config!} onChange={onChange} showNeighbors />}
            {currentType === DetectorType.ENSEMBLE && <EnsembleEditor config={config!} onChange={onChange} />}

            {showPreprocessing && currentType !== DetectorType.ENSEMBLE && currentType !== DetectorType.THRESHOLD && (
                <PreprocessingEditor
                    preprocessing={preprocessing}
                    onChange={handlePreprocessingChange}
                    showLags={[
                        DetectorType.ISOLATION_FOREST,
                        DetectorType.ECOD,
                        DetectorType.COPOD,
                        DetectorType.KNN,
                    ].includes(currentType as DetectorType)}
                />
            )}
        </div>
    )
}
