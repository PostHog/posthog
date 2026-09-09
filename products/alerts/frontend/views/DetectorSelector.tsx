import { IconInfo, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSelect, LemonSegmentedButton, Tooltip } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import {
    AlertCalculationInterval,
    COPODDetectorConfig,
    DetectorConfig,
    DetectorType,
    ECODDetectorConfig,
    EnsembleDetectorConfig,
    EnsembleOperator,
    EnsembleSubDetectorConfig,
    HBOSDetectorConfig,
    IQRDetectorConfig,
    IsolationForestDetectorConfig,
    KNNDetectorConfig,
    LLMDetectorConfig,
    LOFDetectorConfig,
    MADDetectorConfig,
    OCSVMDetectorConfig,
    PCADetectorConfig,
    PreprocessingConfig,
    SingleDetectorConfig,
    ZScoreDetectorConfig,
} from '~/queries/schema/schema-general'

import {
    DEFAULT_ANOMALY_DETECTION_THRESHOLD,
    DEFAULT_LLM_DETECTION_CONFIDENCE,
    MAX_LLM_DETECTOR_WINDOW,
    getDefaultLLMDetectorConfig,
    getDefaultZScoreDetectorConfig,
    getDefaultWindow,
} from '../logic/detectorConfigDefaults'

interface DetectorSelectorProps {
    value: DetectorConfig | null
    onChange: (config: DetectorConfig | null) => void
    calculationInterval?: AlertCalculationInterval
    /** Show the AI detector option. Off until the alerts-llm-detector flag is on for the account. */
    llmDetectorEnabled?: boolean
    /** The insight has a breakdown. The AI detector judges one series, so it is hidden here. */
    hasBreakdown?: boolean
}

const DETECTOR_OPTIONS: Array<{ value: string; label: string; tooltip: string }> = [
    {
        value: DetectorType.LLM,
        label: 'AI judgment',
        tooltip:
            'Shows the recent series to an AI model and asks whether anything looks wrong. Pick this when you want to watch a metric without choosing a statistical method, or when what counts as odd is easier to describe than to measure.',
    },
    {
        value: DetectorType.COPOD,
        label: 'COPOD',
        tooltip:
            'Scores each point against the historical distribution using copulas. Useful when you want a distribution-based detector.',
    },
    {
        value: DetectorType.ECOD,
        label: 'ECOD',
        tooltip:
            'Scores each point against the empirical distribution of past values. Useful when you want an explainable distribution-based detector.',
    },
    {
        value: 'ensemble',
        label: 'Ensemble',
        tooltip:
            'Combine multiple detectors with AND/OR logic. Use AND to reduce false alarms (all detectors must agree) or OR to catch a wider range of anomalies (any detector flags).',
    },
    {
        value: DetectorType.HBOS,
        label: 'HBOS',
        tooltip:
            'Very fast histogram-based detection. Pick this for high-volume alerting where speed matters more than precision.',
    },
    {
        value: DetectorType.IQR,
        label: 'IQR',
        tooltip:
            'Flags values outside the typical range, the same way a box plot does. Robust to existing outliers and works without picking a sensitivity threshold.',
    },
    {
        value: DetectorType.ISOLATION_FOREST,
        label: 'Isolation Forest',
        tooltip:
            'Detects points that look unusual across multiple features. Best for metrics with complex patterns or when combined with lag features.',
    },
    {
        value: DetectorType.KNN,
        label: 'KNN',
        tooltip:
            'Compares each point to its nearest neighbors in recent history. Good for catching points that are unlike anything seen recently.',
    },
    {
        value: DetectorType.LOF,
        label: 'LOF',
        tooltip:
            'Compares each point\'s local density against its neighbors. Best for seasonal or cyclical data where "normal" depends on local context.',
    },
    {
        value: DetectorType.MAD,
        label: 'MAD',
        tooltip:
            "Like Z-Score but uses the median instead of the mean. Choose this if your data already contains spikes you don't want skewing the baseline.",
    },
    {
        value: DetectorType.OCSVM,
        label: 'OCSVM',
        tooltip:
            'Learns the shape of normal data and flags anything outside it. Good for noisy metrics where simple thresholds produce too many false alarms.',
    },
    {
        value: DetectorType.PCA,
        label: 'PCA',
        tooltip:
            "Reduces data to its main patterns and flags points that don't fit. Useful when normal behavior has a few dominant trends.",
    },
    {
        value: DetectorType.THRESHOLD,
        label: 'Threshold',
        tooltip:
            'Alerts when the value crosses a fixed upper or lower bound. Use when you already know the safe range (e.g. "error rate above 5%").',
    },
    {
        value: DetectorType.ZSCORE,
        label: 'Z-Score',
        tooltip:
            "Flags points that are unusually far from the rolling average. Good general-purpose detector — start here if you're not sure which to pick.",
    },
]

// Matches MAX_DETECTOR_INSTRUCTIONS_CHARS on the API, so the field cannot outgrow what saves.
const MAX_LLM_INSTRUCTIONS_CHARS = 2000

const SINGLE_DETECTOR_OPTIONS = DETECTOR_OPTIONS.filter((o) => o.value !== 'ensemble')

// Every check of an ensemble scores every sub-detector, so one AI sub-detector would mean a
// model call on every check. Left out until there's a budget model for it.
const ENSEMBLE_SUB_DETECTOR_OPTIONS = SINGLE_DETECTOR_OPTIONS.filter((o) => o.value !== DetectorType.LLM)

function getDefaultSingleConfigs(window: number): Record<string, SingleDetectorConfig> {
    return {
        zscore: getDefaultZScoreDetectorConfig(window),
        mad: {
            type: 'mad',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            window,
            preprocessing: { diffs_n: 1 },
        },
        iqr: { type: 'iqr', multiplier: 1.5, window },
        llm: getDefaultLLMDetectorConfig(window),
        threshold: { type: 'threshold' },
        ecod: { type: 'ecod', threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD, window },
        copod: { type: 'copod', threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD, window },
        isolation_forest: {
            type: 'isolation_forest',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            n_estimators: 100,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        knn: {
            type: 'knn',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            n_neighbors: 5,
            method: 'largest',
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        lof: {
            type: 'lof',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            n_neighbors: 20,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        hbos: { type: 'hbos', threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD, n_bins: 10, window },
        ocsvm: {
            type: 'ocsvm',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
        pca: {
            type: 'pca',
            threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
            window,
            preprocessing: { diffs_n: 1, lags_n: 3 },
        },
    }
}

function getDefaultEnsemble(window: number): EnsembleDetectorConfig {
    return {
        type: 'ensemble',
        operator: EnsembleOperator.AND,
        detectors: [
            getDefaultZScoreDetectorConfig(window),
            {
                type: 'mad',
                threshold: DEFAULT_ANOMALY_DETECTION_THRESHOLD,
                window,
                preprocessing: { diffs_n: 1 },
            },
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

export function DetectorSelector({
    value,
    onChange,
    calculationInterval,
    llmDetectorEnabled = false,
    hasBreakdown = false,
}: DetectorSelectorProps): JSX.Element {
    const selectedType = getSelectedType(value)
    const defaultWindow = getDefaultWindow(calculationInterval)
    const defaultConfigs = getDefaultSingleConfigs(defaultWindow)
    // An alert already saved with the AI detector keeps showing it even if the flag is turned
    // off, so its own type never disappears from the picker it is selected in.
    const llmAllowed = llmDetectorEnabled && !hasBreakdown && calculationInterval !== AlertCalculationInterval.REAL_TIME
    const detectorOptions = DETECTOR_OPTIONS.filter(
        (o) => o.value !== DetectorType.LLM || llmAllowed || selectedType === DetectorType.LLM
    )

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
                <Label
                    text="Detector"
                    tooltip="Statistical method used to identify anomalies in your data. Hover each option for a description, or start with Z-Score if you're not sure."
                />
                <LemonSelect
                    data-attr="alertForm-detector-type"
                    value={selectedType}
                    onChange={handleTypeChange}
                    options={detectorOptions.map((o) => ({
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

    const getEnsembleDefault = (type: string): EnsembleSubDetectorConfig => {
        const defaultConfig = defaults[type]
        return defaultConfig && defaultConfig.type !== DetectorType.LLM
            ? defaultConfig
            : getDefaultZScoreDetectorConfig(getDefaultWindow(calculationInterval))
    }

    const handleOperatorChange = (newOperator: string): void => {
        onChange({ ...config, operator: newOperator as EnsembleOperator })
    }

    const handleDetectorChange = (index: number, updated: EnsembleSubDetectorConfig): void => {
        const newDetectors = [...detectors]
        newDetectors[index] = updated
        onChange({ ...config, detectors: newDetectors })
    }

    const handleDetectorTypeChange = (index: number, type: string): void => {
        const newDetectors = [...detectors]
        newDetectors[index] = getEnsembleDefault(type)
        onChange({ ...config, detectors: newDetectors })
    }

    const handleAddDetector = (): void => {
        const usedTypes = new Set(detectors.map((d) => d.type))
        const nextType =
            ENSEMBLE_SUB_DETECTOR_OPTIONS.find((o) => !usedTypes.has(o.value as EnsembleSubDetectorConfig['type']))
                ?.value ?? 'zscore'
        onChange({ ...config, detectors: [...detectors, getEnsembleDefault(nextType)] })
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
                    data-attr="alertForm-detector-ensemble-operator"
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
                            data-attr="alertForm-detector-ensemble-sub-type"
                            value={detector.type}
                            onChange={(type) => handleDetectorTypeChange(index, type)}
                            options={ENSEMBLE_SUB_DETECTOR_OPTIONS.map((o) => ({
                                value: o.value,
                                label: o.label,
                                tooltip: o.tooltip,
                            }))}
                            size="small"
                            className="flex-1"
                        />
                        {detectors.length > 2 && (
                            <LemonButton
                                data-attr="alertForm-detector-ensemble-remove"
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
                        onChange={(updated) => {
                            if (updated.type !== DetectorType.LLM) {
                                handleDetectorChange(index, updated)
                            }
                        }}
                        calculationInterval={calculationInterval}
                    />
                </div>
            ))}

            <LemonButton
                data-attr="alertForm-detector-ensemble-add"
                type="secondary"
                icon={<IconPlus />}
                size="small"
                onClick={handleAddDetector}
            >
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
                    <AnomalyThresholdInput
                        value={
                            (config as ZScoreDetectorConfig | MADDetectorConfig).threshold ??
                            DEFAULT_ANOMALY_DETECTION_THRESHOLD
                        }
                        onChange={(val) => onChange({ ...config, threshold: val } as SingleDetectorConfig)}
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
            {config.type === 'llm' && (
                <LLMConfig
                    config={config as LLMDetectorConfig}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                    calculationInterval={calculationInterval}
                />
            )}
            {/* The AI detector reads the series as it is, so it has no preprocessing to configure:
                differencing or smoothing would hide the shape it is meant to judge. */}
            {config.type !== 'llm' && (
                <PreprocessingSection
                    config={config}
                    onChange={(updated) => onChange(updated as SingleDetectorConfig)}
                />
            )}
        </div>
    )
}

function LLMConfig({
    config,
    onChange,
    calculationInterval,
}: {
    config: LLMDetectorConfig
    onChange: (config: DetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
}): JSX.Element {
    return (
        <div className="space-y-3 pl-4 border-l-2 border-border">
            <div>
                <Label
                    text="What counts as unusual?"
                    tooltip="Optional. Anything the model should know about this metric, in your own words. It sees the recent values and a chart of them either way."
                />
                <LemonTextArea
                    data-attr="alertForm-detector-llm-instructions"
                    value={config.instructions ?? ''}
                    onChange={(instructions) => onChange({ ...config, instructions: instructions || undefined })}
                    maxLength={MAX_LLM_INSTRUCTIONS_CHARS}
                    minRows={3}
                    placeholder='For example: "Only tell me about drops" or "Weekends are always quiet, ignore that"'
                />
            </div>
            <div>
                <Label
                    text="Confidence to alert"
                    tooltip="How sure the model has to be before you get an alert (0-1). Higher values mean fewer alerts."
                />
                <LemonInput
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={config.threshold ?? DEFAULT_LLM_DETECTION_CONFIDENCE}
                    onChange={(val) =>
                        onChange({
                            ...config,
                            threshold: val == null ? DEFAULT_LLM_DETECTION_CONFIDENCE : parseFloat(String(val)),
                        })
                    }
                />
            </div>
            <WindowSizeInput
                config={config}
                onChange={onChange}
                calculationInterval={calculationInterval}
                max={MAX_LLM_DETECTOR_WINDOW}
                defaultWindow={Math.min(getDefaultWindow(calculationInterval), MAX_LLM_DETECTOR_WINDOW)}
                tooltip="How many recent data points the model is shown. Larger gives it more history to compare against, and costs more per check."
            />
            <p className="text-xs text-muted">
                Each check sends the recent values and a chart of them to an AI model, which is slower and costs more
                than the statistical detectors.
            </p>
        </div>
    )
}

function AnomalyThresholdInput({ value, onChange }: { value: number; onChange: (value: number) => void }): JSX.Element {
    return (
        <div>
            <Label
                text="Anomaly threshold"
                tooltip="Minimum anomaly probability required to trigger an alert (0-1). Higher values trigger fewer alerts."
            />
            <LemonInput
                type="number"
                min={0.5}
                max={0.99}
                step={0.05}
                value={value}
                onChange={(val) => onChange(val ? parseFloat(String(val)) : DEFAULT_ANOMALY_DETECTION_THRESHOLD)}
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
            <AnomalyThresholdInput
                value={config.threshold ?? DEFAULT_ANOMALY_DETECTION_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
            />
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">Empirical cumulative distribution for interpretable anomaly scoring.</p>
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
            <AnomalyThresholdInput
                value={config.threshold ?? DEFAULT_ANOMALY_DETECTION_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
            />
            <WindowSizeInput config={config} onChange={onChange} calculationInterval={calculationInterval} />
            <p className="text-xs text-muted">Efficient copula-based anomaly scoring.</p>
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
            <AnomalyThresholdInput
                value={config.threshold ?? DEFAULT_ANOMALY_DETECTION_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
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
            <AnomalyThresholdInput
                value={config.threshold ?? DEFAULT_ANOMALY_DETECTION_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
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
            <AnomalyThresholdInput
                value={config.threshold ?? DEFAULT_ANOMALY_DETECTION_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
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
            <AnomalyThresholdInput
                value={config.threshold ?? DEFAULT_ANOMALY_DETECTION_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
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
            <AnomalyThresholdInput
                value={config.threshold ?? DEFAULT_ANOMALY_DETECTION_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
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
            <AnomalyThresholdInput
                value={config.threshold ?? DEFAULT_ANOMALY_DETECTION_THRESHOLD}
                onChange={(val) => onChange({ ...config, threshold: val })}
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
    max = 1000,
    defaultWindow,
    tooltip = 'Number of historical data points used to calculate the baseline. Larger = more stable, smaller = more responsive.',
}: {
    config: { window?: number }
    onChange: (config: SingleDetectorConfig) => void
    calculationInterval?: AlertCalculationInterval
    max?: number
    defaultWindow?: number
    /** Override when the window does not describe a training baseline (the AI detector reads the points). */
    tooltip?: string
}): JSX.Element {
    const defWindow = defaultWindow ?? getDefaultWindow(calculationInterval)
    return (
        <div>
            <Label text="Window size" tooltip={tooltip} />
            <LemonInput
                type="number"
                min={5}
                max={max}
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
    // The AI detector has no preprocessing to configure, so it never reaches this section.
    config: Exclude<SingleDetectorConfig, LLMDetectorConfig>
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
