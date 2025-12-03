import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { DetectorType, InsightThresholdType, ThresholdDetectorConfig } from '~/queries/schema/schema-general'

export interface ThresholdDetectorFormProps {
    config: ThresholdDetectorConfig
    onChange: (config: ThresholdDetectorConfig) => void
}

export function ThresholdDetectorForm({ config, onChange }: ThresholdDetectorFormProps): JSX.Element {
    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <span className="text-sm font-medium w-24">Type:</span>
                <LemonSelect
                    value={config.threshold_type}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            threshold_type: value as InsightThresholdType,
                        })
                    }
                    options={[
                        { value: InsightThresholdType.ABSOLUTE, label: 'Absolute value' },
                        { value: InsightThresholdType.PERCENTAGE, label: 'Percentage' },
                    ]}
                    size="small"
                />
            </div>

            <div className="flex items-center gap-2">
                <span className="text-sm font-medium w-24">Lower bound:</span>
                <LemonInput
                    type="number"
                    value={config.bounds?.lower ?? ''}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            bounds: {
                                ...config.bounds,
                                lower: value === '' ? undefined : Number(value),
                            },
                        })
                    }
                    placeholder="No lower bound"
                    size="small"
                    className="w-32"
                />
                {config.threshold_type === InsightThresholdType.PERCENTAGE && <span>%</span>}
            </div>

            <div className="flex items-center gap-2">
                <span className="text-sm font-medium w-24">Upper bound:</span>
                <LemonInput
                    type="number"
                    value={config.bounds?.upper ?? ''}
                    onChange={(value) =>
                        onChange({
                            ...config,
                            bounds: {
                                ...config.bounds,
                                upper: value === '' ? undefined : Number(value),
                            },
                        })
                    }
                    placeholder="No upper bound"
                    size="small"
                    className="w-32"
                />
                {config.threshold_type === InsightThresholdType.PERCENTAGE && <span>%</span>}
            </div>
        </div>
    )
}

export function createDefaultThresholdConfig(): ThresholdDetectorConfig {
    return {
        type: DetectorType.THRESHOLD,
        threshold_type: InsightThresholdType.ABSOLUTE,
        bounds: {
            lower: undefined,
            upper: undefined,
        },
    }
}
