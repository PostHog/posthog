import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import {
    AlertCalculationInterval,
    ForecastConditionType,
    ForecastConfig,
    ForecastEngineType,
    ForecastSensitivity,
    ForecastTargetDirection,
} from '~/queries/schema/schema-general'

import { forecastTargetDateError, maxHorizonForInterval } from 'products/alerts/frontend/logic/forecastReach'

const HORIZON_UNIT: Record<AlertCalculationInterval, string> = {
    [AlertCalculationInterval.REAL_TIME]: 'intervals',
    [AlertCalculationInterval.EVERY_15_MINUTES]: 'intervals',
    [AlertCalculationInterval.HOURLY]: 'hours',
    [AlertCalculationInterval.DAILY]: 'days',
    [AlertCalculationInterval.WEEKLY]: 'weeks',
    [AlertCalculationInterval.MONTHLY]: 'months',
}

/** Default lookahead window for a "predicted to breach" forecast, in calculation-interval units. */
const DEFAULT_HORIZON = 7
/** Default band width, matching the "Wider" option that fires only on clear deviations. */
const DEFAULT_INTERVAL_WIDTH = 0.95
/** Default runway for a new target, comfortably inside the six month reach cap. */
const DEFAULT_TARGET_DAYS = 90

/** Mirrors _resolve_sensitivity in products/alerts/backend/evaluation/forecast.py. A target has months
 *  of runway so flapping is the failure mode; a predicted breach exists for lead time, so it keeps the
 *  point forecast and its firing does not move. */
export function defaultSensitivity(condition: ForecastConditionType): ForecastSensitivity {
    return condition === ForecastConditionType.TARGET_BY_DATE
        ? ForecastSensitivity.BEST_CASE
        : ForecastSensitivity.FORECAST
}

/** Seeds the fields a condition needs when the user switches to it, so a target starts with a date
 *  already in range rather than an empty control the save path would reject. */
export function withConditionDefaults(config: ForecastConfig, condition: ForecastConditionType): ForecastConfig {
    if (condition !== ForecastConditionType.TARGET_BY_DATE) {
        return { ...config, condition }
    }
    return {
        ...config,
        condition,
        target_direction: config.target_direction ?? ForecastTargetDirection.AT_LEAST,
        target_date: config.target_date ?? dayjs().add(DEFAULT_TARGET_DAYS, 'day').format('YYYY-MM-DD'),
    }
}

export function getDefaultForecastConfig(): ForecastConfig {
    return {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: DEFAULT_HORIZON,
        interval_width: DEFAULT_INTERVAL_WIDTH,
    }
}

/** A setting's label with an info balloon saying what the setting is for, rather than what it does.
 *  The per-option tooltips already cover the mechanics. */
function SettingHelp({ text }: { text: string }): JSX.Element {
    return (
        <Tooltip title={text} delayMs={0}>
            <IconInfo className="text-muted size-3.5" />
        </Tooltip>
    )
}

interface ForecastSelectorProps {
    value: ForecastConfig | null
    onChange: (config: ForecastConfig) => void
    calculationInterval: AlertCalculationInterval
}

export function ForecastSelector({ value, onChange, calculationInterval }: ForecastSelectorProps): JSX.Element {
    const config = value ?? getDefaultForecastConfig()
    const unit = HORIZON_UNIT[calculationInterval] ?? 'intervals'
    // The backend caps how far a forecast reaches as a duration, so this ceiling moves with the
    // insight's interval. Clamping on change stops a horizon surviving a switch to a coarser one.
    const maxHorizon = maxHorizonForInterval(calculationInterval)
    const targetDateError = forecastTargetDateError(config.target_date, new Date())
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <LemonSelect
                data-attr="alertForm-forecast-condition"
                value={config.condition}
                onChange={(condition) => onChange(withConditionDefaults(config, condition))}
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
                            'Alert when the latest value falls outside the forecasted range. This is a seasonality-aware anomaly check.',
                    },
                    {
                        label: 'On track for a target',
                        value: ForecastConditionType.TARGET_BY_DATE,
                        tooltip: 'Alert when the value forecast for a date you set misses a number you set.',
                    },
                ]}
            />
            <SettingHelp text="What counts as a problem: heading for a limit, abnormal right now, or not on course for a number." />
            {config.condition === ForecastConditionType.TARGET_BY_DATE && (
                <div className="flex flex-wrap items-center gap-2">
                    <SettingHelp text="The value this metric should reach on that date. Use at least for goals such as active users, and at most for budgets such as churn. For a running total rather than the value on the day, point this at a cumulative insight." />
                    <LemonSelect
                        data-attr="alertForm-forecast-target-direction"
                        value={config.target_direction ?? ForecastTargetDirection.AT_LEAST}
                        onChange={(target_direction) => onChange({ ...config, target_direction })}
                        options={[
                            { label: 'at least', value: ForecastTargetDirection.AT_LEAST },
                            { label: 'at most', value: ForecastTargetDirection.AT_MOST },
                        ]}
                    />
                    <LemonInput
                        type="number"
                        className="w-24"
                        data-attr="alertForm-forecast-target"
                        value={config.target ?? undefined}
                        onChange={(target) => onChange({ ...config, target: target ?? undefined })}
                    />
                    <span className="whitespace-nowrap">on</span>
                    <LemonCalendarSelectInput
                        data-attr="alertForm-forecast-target-date"
                        value={config.target_date ? dayjs(config.target_date) : null}
                        onChange={(d) => onChange({ ...config, target_date: d ? d.format('YYYY-MM-DD') : undefined })}
                    />
                    {targetDateError ? (
                        <div className="w-full text-danger text-xs" data-attr="alertForm-forecast-target-date-error">
                            {targetDateError}
                        </div>
                    ) : null}
                </div>
            )}
            {config.condition === ForecastConditionType.FUTURE_BREACH && (
                <div className="flex items-center gap-2">
                    <span className="whitespace-nowrap">within the next</span>
                    <LemonInput
                        type="number"
                        className="w-20"
                        data-attr="alertForm-forecast-horizon"
                        min={1}
                        max={maxHorizon}
                        value={Math.min(config.horizon ?? DEFAULT_HORIZON, maxHorizon)}
                        onChange={(horizon) =>
                            onChange({ ...config, horizon: Math.min(horizon ?? DEFAULT_HORIZON, maxHorizon) })
                        }
                    />
                    <span>{unit}</span>
                    <SettingHelp text="How far ahead to look. A shorter window is more reliable, a longer one gives you more time to react." />
                </div>
            )}
            {/* The label and its control wrap as one unit, so the label never strands on the row above. */}
            {config.condition === ForecastConditionType.BAND_DEVIATION ? (
                <div className="flex items-center gap-2">
                    <span className="text-secondary whitespace-nowrap">Expected range</span>
                    <SettingHelp text="How far from normal counts as unusual. Narrower catches smaller dips and fires more often." />
                    <LemonSegmentedButton
                        size="small"
                        data-attr="alertForm-forecast-interval-width"
                        value={config.interval_width ?? DEFAULT_INTERVAL_WIDTH}
                        onChange={(interval_width) => onChange({ ...config, interval_width })}
                        options={[
                            {
                                value: 0.8,
                                label: 'Narrower',
                                tooltip: 'More sensitive. Fires on smaller deviations, with more noise.',
                            },
                            {
                                value: DEFAULT_INTERVAL_WIDTH,
                                label: 'Wider',
                                tooltip: 'Fires only on clear deviations.',
                            },
                        ]}
                    />
                </div>
            ) : (
                /* The band width does not decide when these two fire; which line they read does. */
                <div className="flex items-center gap-2">
                    <span className="text-secondary whitespace-nowrap">Alert when</span>
                    <SettingHelp text="How certain to be before alerting. Best case waits until the outcome can no longer be avoided, so it fires less often." />
                    <LemonSegmentedButton
                        size="small"
                        data-attr="alertForm-forecast-sensitivity"
                        value={config.sensitivity ?? defaultSensitivity(config.condition)}
                        onChange={(sensitivity) => onChange({ ...config, sensitivity })}
                        options={[
                            {
                                value: ForecastSensitivity.FORECAST,
                                label: 'Forecast',
                                tooltip: 'Warns earlier, and can change its mind while the forecast is uncertain.',
                            },
                            {
                                value: ForecastSensitivity.BEST_CASE,
                                label: 'Best case',
                                tooltip: 'Quieter. Waits until the outcome is no longer avoidable.',
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
