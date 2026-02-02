import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import {
    COPODDetectorConfig,
    DetectorConfig,
    DetectorType,
    ECODDetectorConfig,
    IQRDetectorConfig,
    IsolationForestDetectorConfig,
    KNNDetectorConfig,
    MADDetectorConfig,
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
        description: 'Median Absolute Deviation - robust to outliers',
    },
    {
        value: DetectorType.IQR,
        label: 'IQR',
        description: 'Interquartile Range - classic box plot method',
    },
    {
        value: DetectorType.THRESHOLD,
        label: 'Threshold',
        description: 'Simple upper/lower bounds',
    },
    {
        value: DetectorType.ECOD,
        label: 'ECOD',
        description: 'Empirical Cumulative Distribution',
    },
    {
        value: DetectorType.COPOD,
        label: 'COPOD',
        description: 'Copula-based Outlier Detection',
    },
    {
        value: DetectorType.ISOLATION_FOREST,
        label: 'Isolation Forest',
        description: 'Tree-based anomaly isolation',
    },
    {
        value: DetectorType.KNN,
        label: 'KNN',
        description: 'K-Nearest Neighbors distance',
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
                onChange({ type: 'zscore', threshold: 3.0, window: 30 } as ZScoreDetectorConfig)
                break
            case DetectorType.MAD:
                onChange({ type: 'mad', threshold: 3.0, window: 30 } as MADDetectorConfig)
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
            {value?.type === 'mad' && <MADConfig config={value as MADDetectorConfig} onChange={onChange} />}
            {value?.type === 'iqr' && <IQRConfig config={value as IQRDetectorConfig} onChange={onChange} />}
            {value?.type === 'threshold' && (
                <ThresholdConfig config={value as ThresholdDetectorConfig} onChange={onChange} />
            )}
            {value?.type === 'ecod' && <ECODConfig config={value as ECODDetectorConfig} onChange={onChange} />}
            {value?.type === 'copod' && <COPODConfig config={value as COPODDetectorConfig} onChange={onChange} />}
            {value?.type === 'isolation_forest' && (
                <IsolationForestConfig config={value as IsolationForestDetectorConfig} onChange={onChange} />
            )}
            {value?.type === 'knn' && <KNNConfig config={value as KNNDetectorConfig} onChange={onChange} />}
        </div>
    )
}

// Statistical detector configs

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
                    Threshold (scaled MADs)
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
                    Uses median instead of mean - more robust to existing outliers in data.
                </p>
            </div>
            <WindowSizeInput config={config} onChange={onChange} />
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
                    IQR Multiplier
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

// PyOD detector configs

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
            <p className="text-xs text-muted">Empirical Cumulative Distribution - parameter-free and interpretable.</p>
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

// Shared input components

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
