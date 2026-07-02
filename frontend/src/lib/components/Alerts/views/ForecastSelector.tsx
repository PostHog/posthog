import { LemonInput, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import {
    AlertCalculationInterval,
    ForecastConditionType,
    ForecastConfig,
    ForecastEngineType,
} from '~/queries/schema/schema-general'

const HORIZON_UNIT: Record<AlertCalculationInterval, string> = {
    [AlertCalculationInterval.EVERY_15_MINUTES]: 'intervals',
    [AlertCalculationInterval.HOURLY]: 'hours',
    [AlertCalculationInterval.DAILY]: 'days',
    [AlertCalculationInterval.WEEKLY]: 'weeks',
    [AlertCalculationInterval.MONTHLY]: 'months',
}

export function getDefaultForecastConfig(): ForecastConfig {
    return {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: 7,
        interval_width: 0.95,
    }
}

interface ForecastSelectorProps {
    value: ForecastConfig | null
    onChange: (config: ForecastConfig) => void
    calculationInterval: AlertCalculationInterval
}

export function ForecastSelector({ value, onChange, calculationInterval }: ForecastSelectorProps): JSX.Element {
    const config = value ?? getDefaultForecastConfig()
    const unit = HORIZON_UNIT[calculationInterval] ?? 'intervals'
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <LemonSelect
                data-attr="alertForm-forecast-condition"
                value={config.condition}
                onChange={(condition) => onChange({ ...config, condition })}
                options={[
                    {
                        label: 'Predicted to breach threshold',
                        value: ForecastConditionType.FUTURE_BREACH,
                        tooltip: 'Alert when the forecast says the metric will cross your threshold soon.',
                    },
                    {
                        label: 'Outside expected range',
                        value: ForecastConditionType.BAND_DEVIATION,
                        tooltip:
                            'Alert when the latest value falls outside the forecasted range — a seasonality-aware anomaly check.',
                    },
                ]}
            />
            {config.condition === ForecastConditionType.FUTURE_BREACH && (
                <>
                    <span>within the next</span>
                    <LemonInput
                        type="number"
                        className="w-20"
                        data-attr="alertForm-forecast-horizon"
                        min={1}
                        max={30}
                        value={config.horizon ?? 7}
                        onChange={(horizon) => onChange({ ...config, horizon: horizon ?? 7 })}
                    />
                    <span>{unit}</span>
                </>
            )}
            <span className="text-secondary">Expected range</span>
            <LemonSegmentedButton
                size="small"
                value={config.interval_width ?? 0.95}
                onChange={(interval_width) => onChange({ ...config, interval_width })}
                options={[
                    {
                        value: 0.8,
                        label: 'Narrower',
                        tooltip: 'More sensitive — fires on smaller deviations, more noise.',
                    },
                    { value: 0.95, label: 'Wider', tooltip: 'Fires only on clear deviations.' },
                ]}
            />
        </div>
    )
}
