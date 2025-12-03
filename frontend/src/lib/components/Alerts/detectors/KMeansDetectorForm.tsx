import { LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import {
    DetectorType,
    KMeansAnomalyMethod,
    KMeansDetectorConfig,
    KMeansFeature,
} from '~/queries/schema/schema-general'

export interface KMeansDetectorFormProps {
    config: KMeansDetectorConfig
    onChange: (config: KMeansDetectorConfig) => void
}

const FEATURE_OPTIONS: { value: KMeansFeature; label: string; description: string }[] = [
    { value: KMeansFeature.DIFF_1, label: 'Diff (t - t-1)', description: 'First difference' },
    { value: KMeansFeature.LAG_1, label: 'Lag 1', description: 'Value at t-1' },
    { value: KMeansFeature.LAG_2, label: 'Lag 2', description: 'Value at t-2' },
    { value: KMeansFeature.LAG_3, label: 'Lag 3', description: 'Value at t-3' },
    { value: KMeansFeature.LAG_4, label: 'Lag 4', description: 'Value at t-4' },
    { value: KMeansFeature.LAG_5, label: 'Lag 5', description: 'Value at t-5' },
    { value: KMeansFeature.SMOOTHED_3, label: 'Smoothed 3', description: '3-period moving average' },
    { value: KMeansFeature.SMOOTHED_5, label: 'Smoothed 5', description: '5-period moving average' },
    { value: KMeansFeature.SMOOTHED_7, label: 'Smoothed 7', description: '7-period moving average' },
]

export function KMeansDetectorForm({ config, onChange }: KMeansDetectorFormProps): JSX.Element {
    const toggleFeature = (feature: KMeansFeature): void => {
        const currentFeatures = config.features || []
        const newFeatures = currentFeatures.includes(feature)
            ? currentFeatures.filter((f) => f !== feature)
            : [...currentFeatures, feature]
        onChange({
            ...config,
            features: newFeatures,
        })
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium w-28">Clusters:</span>
                <LemonInput
                    type="number"
                    value={config.n_clusters}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            n_clusters: Number(value) || 3,
                        })
                    }
                    min={2}
                    max={10}
                    size="small"
                    className="w-20"
                />
            </div>

            <div className="flex items-center gap-2">
                <span className="text-sm font-medium w-28">Anomaly method:</span>
                <LemonSelect
                    value={config.anomaly_method}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            anomaly_method: value as KMeansAnomalyMethod,
                        })
                    }
                    options={[
                        { value: KMeansAnomalyMethod.SMALLEST, label: 'Smallest cluster' },
                        { value: KMeansAnomalyMethod.FURTHEST, label: 'Furthest from mean' },
                    ]}
                    size="small"
                />
            </div>

            <div>
                <span className="text-sm font-medium">Feature vector components:</span>
                <div className="mt-2 grid grid-cols-3 gap-2">
                    {FEATURE_OPTIONS.map((option) => (
                        <LemonCheckbox
                            key={option.value}
                            checked={config.features?.includes(option.value) ?? false}
                            onChange={() => toggleFeature(option.value)}
                            label={
                                <span title={option.description} className="text-sm">
                                    {option.label}
                                </span>
                            }
                            size="small"
                        />
                    ))}
                </div>
            </div>

            {(config.features?.length ?? 0) < 2 && (
                <div className="text-xs text-warning bg-warning-highlight p-2 rounded">
                    Select at least 2 features for meaningful clustering
                </div>
            )}

            <div className="text-xs text-muted bg-bg-light p-2 rounded">
                Builds feature vectors from the selected components and clusters them using K-Means. Points in the{' '}
                {config.anomaly_method === KMeansAnomalyMethod.SMALLEST ? 'smallest' : 'most distant'} cluster are
                flagged as anomalies.
            </div>
        </div>
    )
}

export function createDefaultKMeansConfig(): KMeansDetectorConfig {
    return {
        type: DetectorType.KMEANS,
        n_clusters: 3,
        features: [KMeansFeature.DIFF_1, KMeansFeature.LAG_1, KMeansFeature.LAG_2, KMeansFeature.SMOOTHED_3],
        anomaly_method: KMeansAnomalyMethod.SMALLEST,
    }
}
