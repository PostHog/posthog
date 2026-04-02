import { IconInfo, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import {
    AlertCalculationInterval,
    COPODDetectorConfig,
    DetectorConfig,
    DetectorType,
    ECODDetectorConfig,
    EnsembleDetectorConfig,
    EnsembleOperator,
    HBOSDetectorConfig,
    IQRDetectorConfig,
    IsolationForestDetectorConfig,
    KNNDetectorConfig,
    LOFDetectorConfig,
    MADDetectorConfig,
    OCSVMDetectorConfig,
    PCADetectorConfig,
    PreprocessingConfig,
    SingleDetectorConfig,
    ZScoreDetectorConfig,
} from '~/queries/schema/schema-general'

/** Default anomaly probability threshold for all detectors. Higher = fewer alerts. */
const DEFAULT_THRESHOLD = 0.95

/** Default window size based on how often the alert checks.
 *  Hourly: 168 (7 days), Daily: 90, Weekly: 26 (6 months), Monthly: 12 (1 year). */
export function getDefaultWindow(interval?: AlertCalculationInterval): number {
    switch (interval) {
        case AlertCalculationInterval.HOURLY:
            return 168
        case AlertCalculationInterval.WEEKLY:
            return 26
        case AlertCalculationInterval.MONTHLY:
            return 12
        default:
            return 90
    }
}

interface DetectorSelectorProps {
    value: DetectorConfig | null
    onChange: (config: DetectorConfig | null) => void
    calculationInterval?: AlertCalculationInterval
}

const DETECTOR_OPTIONS: Array<{ value: string; label: string; tooltip: string }> = [
    {
        value: DetectorType.COPOD,
        label: 'COPOD',
        tooltip: 'Copula-based outlier detection — efficient and parameter-free.',
    },
    {
        value: DetectorType.ECOD,
        label: 'ECOD',
        tooltip: 'Empirical cumulative distribution — parameter-free and interpretable.',
    },
    {
        value: 'ensemble',
        label: 'Ensemble',
        tooltip: 'Combine multiple detectors with AND/OR logic for more precise anomaly detection.',
    },
    {
        value: DetectorType.HBOS,
        label: 'HBOS',
        tooltip: 'Histogram-based outlier score — very fast, good for high-volume alerting.',
    },
    {
        value: DetectorType.IQR,
        label: 'IQR',
        tooltip: 'Interquartile range — classic box plot method for detecting outliers.',
    },
    {
        value: DetectorType.ISOLATION_FOREST,
        label: 'Isolation Forest',
        tooltip: 'Isolates anomalies using random forest — good for complex patterns.',
    },
    {
        value: DetectorType.KNN,
        label: 'KNN',
        tooltip: 'K-nearest neighbors distance — points far from others are anomalies.',
    },
    {
        value: DetectorType.LOF,
        label: 'LOF',
        tooltip: 'Local outlier factor — density-based, good for seasonal data.',
    },
    {
        value: DetectorType.MAD,
        label: 'MAD',
        tooltip:
            'Like Z-Score but uses the median instead of the mean, making it robust to existing outliers in your data.',
    },
    {
        value: DetectorType.OCSVM,
        label: 'OCSVM',
        tooltip: 'One-class SVM — learns a boundary around normal data.',
    },
    {
        value: DetectorType.PCA,
        label: 'PCA',
        tooltip: 'PCA-based — detects anomalies via reconstruction error.',
    },
    {
        value: DetectorType.THRESHOLD,
        label: 'Threshold',
        tooltip: 'Simple upper/lower bounds. Alerts when the value crosses a fixed limit.',
    },
    {
        value: DetectorType.ZSCORE,
        label: 'Z-Score',
        tooltip: 'Flags points that are unusually far from the rolling average. Good general-purpose detector.',
    },
]

const SINGLE_DETECTOR_OPTIONS = DETECTOR_OPTIONS.filter((o) => o.value !== 'ensemble')

function getDefaultSingleConfigs(window: number): Record<string, SingleDetectorConfig> {
    return {
        zscore: { type: 'zscore', threshold: DEFAULT_THRESHOLD, window, preprocessing: { diffs_n: 1 } },
        mad: { type: 'mad', threshold: DEFAULT_THRESHOLD, window, preprocessing: { diffs_n: 1 } },
        iqr: { type: 'iqr', multiplier: 1.5, window },
        threshold: { type: 'threshold' },
        ecod: { type: 'ecod', threshold: DEFAULT_THRESHOLD, window },
        copod: { type: 'copod', threshold: DEFAULT_THRESHOLD, window },
        isolation_forest: {
            type: 'isolation_forest',
            threshold: DEFAULT_THRESHOLD,
            n_estimators: 100,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        knn: {
            type: 'knn',
            threshold: DEFAULT_THRESHOLD,
            n_neighbors: 5,
            method: 'largest',
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        lof: {
            type: 'lof',
            threshold: DEFAULT_THRESHOLD,
            n_neighbors: 20,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        hbos: { type: 'hbos', threshold: DEFAULT_THRESHOLD, n_bins: 10, window },
        ocsvm: { type: 'ocsvm', threshold: DEFAULT_THRESHOLD, window, preprocessing: { diffs_n: 1, lags_n: 3 } },
        pca: { type: 'pca', threshold: DEFAULT_THRESHOLD, window, preprocessing: { diffs_n: 1, lags_n: 3 } },
    }
}

function getDefaultEnsemble(window: number): EnsembleDetectorConfig {
    return {
        type: 'ensemble',
        operator: EnsembleOperator.AND,
        detectors: [
            { type: 'zscore', threshold: DEFAULT_THRESHOLD, window, preprocessing: { diffs_n: 1 } },
            { type: 'mad', threshold: DEFAULT_THRESHOLD, window, preprocessing: { diffs_n: 1 } },
        ],
    }
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

export function DetectorSelector({ value, onChange, calculationInterval }: DetectorSelectorProps): JSX.Element {
    const selectedType = getSelectedType(value)
    const defaultWindow = getDefaultWindow(calculationInterval)
    const defaultConfigs = getDefaultSingleConfigs(defaultWindow)

    const handleTypeChange = (type: string | null): void => {
        if (!type) {
            onChange(null)
            return
        }

        if (type === 'ensemble') {
            onChange(getDefaultEnsemble(defaultWindow))
            return
        }

        const defaultConfig = defaultConfigs[type]
        onChange(defaultConfig ?? null)
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
                <EnsembleConfig
                    config={value as EnsembleDetectorConfig}
                    onChange={onChange}
                    calculationInterval={calculationInterval}
                />
            ) : value && value.type !== 'ensemble' ? (
                <SingleDetectorConfigSection
                    config={value as SingleDetectorConfig}
                    onChange={(updated) => onChange(updated)}
                    calculationInterval={calculationInterval}
                />
            ) : null}
        </div>
    )
}

function EnsembleConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: EnsembleDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    const { operator, detectors } = config
    const defaults = getDefaultSingleConfigs(getDefaultWindow(calculationInterval))

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
        newDetectors[index] = defaults[type] ?? defaults.zscore
        onChange({ ...config, detectors: newDetectors })
    }

    const handleAddDetector = (): void => {
        const usedTypes = new Set(detectors.map((d) => d.type))
        const nextType =
            SINGLE_DETECTOR_OPTIONS.find((o) => !usedTypes.has(o.value as SingleDetectorConfig['type']))?.value ??
            'zscore'
        onChange({ ...config, detectors: [...detectors, defaults[nextType]] })
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
                        calculationInterval={calculationInterval}
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
    calculationInterval,
}: {
    config: SingleDetectorConfig
    onChange: (config: SingleDetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div>
            {(config.type === 'zscore' || config.type === 'mad') && (
                <div className="grid grid-cols-2 gap-3">
                    <SensitivityInput
                        value={(config as ZScoreDetectorConfig | MADDetectorConfig).threshold ?? DEFAULT_THRESHOLD}
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
                        calculationInterval={calculationInterval}
                    />
                </div>
            )}
            {config.type === 'iqr' && (
                <IQRConfig
                    config={config as IQRDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                />
            )}
            {config.type === 'ecod' && (
                <ECODConfig
                    config={config as ECODDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
            )}
            {config.type === 'copod' && (
                <COPODConfig
                    config={config as COPODDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
            )}
            {config.type === 'isolation_forest' && (
                <IsolationForestConfig
                    config={config as IsolationForestDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
            )}
            {config.type === 'knn' && (
                <KNNConfig
                    config={config as KNNDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
            )}
            {config.type === 'lof' && (
                <LOFConfig
                    config={config as LOFDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
            )}
            {config.type === 'hbos' && (
                <HBOSConfig
                    config={config as HBOSDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
            )}
            {config.type === 'ocsvm' && (
                <OCSVMConfig
                    config={config as OCSVMDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
            )}
            {config.type === 'pca' && (
                <PCAConfig
                    config={config as PCADetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
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
                onChange={(val) => onChange(val ? parseFloat(String(val)) : DEFAULT_THRESHOLD)}
            />
        </div>
    )
}

function IQRConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: IQRDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <div>
                <Label
                    text="IQR multiplier"
                    tooltip="How far from the interquartile range a value must be to count as an outlier. 1.5 = standard, 3.0 = extreme only."
                />
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
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
        </div>
    )
}

function ECODConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: ECODDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? DEFAULT_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Higher = fewer alerts."
            />
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">Empirical cumulative distribution — parameter-free and interpretable.</p>
        </div>
    )
}

function COPODConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: COPODDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? DEFAULT_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Higher = fewer alerts."
            />
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">Copula-based detection — efficient and parameter-free.</p>
        </div>
    )
}

function IsolationForestConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: IsolationForestDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? DEFAULT_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Higher = fewer alerts."
            />
            <div>
                <Label text="Number of trees" tooltip="More trees = more accurate but slower. 100 is a good default." />
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
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">Isolates anomalies using random forest — good for complex patterns.</p>
        </div>
    )
}

function KNNConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: KNNDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? DEFAULT_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Higher = fewer alerts."
            />
            <div>
                <Label
                    text="Number of neighbors"
                    tooltip="How many nearest neighbors to consider. More = smoother detection, fewer = more sensitive."
                />
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
                <Label
                    text="Distance method"
                    tooltip="How to aggregate distances to K neighbors. 'Largest' uses the farthest neighbor, 'mean' and 'median' average across all K."
                />
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
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">
                Uses distance to nearest neighbors — points far from others are anomalies.
            </p>
        </div>
    )
}

function LOFConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: LOFDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? DEFAULT_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Higher = fewer alerts."
            />
            <div>
                <Label
                    text="Number of neighbors"
                    tooltip="Size of the local neighborhood for density estimation. 20 is a good default for most time series."
                />
                <LemonInput
                    type="number"
                    min={1}
                    max={50}
                    step={1}
                    value={config.n_neighbors ?? 20}
                    onChange={(val) => onChange({ ...config, n_neighbors: val ? parseInt(String(val), 10) : 20 })}
                    fullWidth
                />
            </div>
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">
                Density-based — compares local density of a point to its neighbors. Good for seasonal data.
            </p>
        </div>
    )
}

function HBOSConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: HBOSDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? DEFAULT_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Higher = fewer alerts."
            />
            <div>
                <Label
                    text="Number of bins"
                    tooltip="How many histogram bins to use. More bins = finer-grained detection but needs more data points."
                />
                <LemonInput
                    type="number"
                    min={5}
                    max={50}
                    step={1}
                    value={config.n_bins ?? 10}
                    onChange={(val) => onChange({ ...config, n_bins: val ? parseInt(String(val), 10) : 10 })}
                    fullWidth
                />
            </div>
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">Very fast histogram-based detection. Good for high-volume alerting.</p>
        </div>
    )
}

function OCSVMConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: OCSVMDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? DEFAULT_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Higher = fewer alerts."
            />
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">
                One-class SVM — learns a boundary around normal data using a support vector machine.
            </p>
        </div>
    )
}

function PCAConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: PCADetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <SensitivityInput
                value={config.threshold ?? DEFAULT_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
                tooltip="Anomaly probability threshold (0-1). Higher = fewer alerts."
            />
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">
                PCA-based — detects anomalies as points with high reconstruction error.
            </p>
        </div>
    )
}

function WindowSizeInput({
    config,
    onChange,
    calculationInterval,
}: {
    config: { window?: number }
    onChange: (config: SingleDetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    const defWindow = getDefaultWindow(calculationInterval)
    return (
        <div>
            <Label
                text="Window size"
                tooltip="Number of historical data points used to calculate the baseline. Larger = more stable, smaller = more responsive."
            />
            <LemonInput
                type="number"
                min={5}
                max={1000}
                step={5}
                value={config.window ?? defWindow}
                onChange={(val) =>
                    onChange({ ...config, window: val ? parseInt(String(val), 10) : defWindow } as SingleDetectorConfig)
                }
            />
        </div>
    )
}

// Detectors that benefit from multivariate input (lag features)
const MULTIVARIATE_DETECTORS = new Set(['knn', 'pca', 'lof', 'ocsvm', 'isolation_forest'])

function PreprocessingSection({
    config,
    onChange,
}: {
    config: SingleDetectorConfig
    onChange: (config: SingleDetectorConfig) => void
}): JSX.Element {
    const preprocessing = config.preprocessing ?? {}
    const isMultivariate = MULTIVARIATE_DETECTORS.has(config.type)
    const hasPreprocessing =
        (preprocessing.diffs_n ?? 0) > 0 || (preprocessing.smooth_n ?? 0) > 0 || (preprocessing.lags_n ?? 0) > 0

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
                                        (preprocessing.lags_n ?? 0) > 0 ? `${preprocessing.lags_n} lags` : null,
                                    ]
                                        .filter(Boolean)
                                        .join(', ')}
                                </span>
                            )}
                        </span>
                    ),
                    content: (
                        <div className="space-y-3">
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
                            {isMultivariate && (
                                <div>
                                    <Label
                                        text="Lag features"
                                        tooltip="Creates a feature vector from recent values (e.g. 5 lags = each point becomes [t, t-1, t-2, t-3, t-4, t-5]). Essential for multivariate detectors like KNN, PCA, and LOF."
                                    />
                                    <LemonInput
                                        type="number"
                                        min={0}
                                        max={10}
                                        step={1}
                                        value={preprocessing.lags_n ?? 0}
                                        onChange={(val) =>
                                            updatePreprocessing({
                                                lags_n: val ? parseInt(String(val), 10) : undefined,
                                            })
                                        }
                                    />
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
            size="small"
            embedded
        />
    )
}
