import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSegmentedButton, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'

import {
    ForecastConditionType,
    ForecastConfig,
    ForecastDirection,
    ForecastErrorMode,
    ForecastEngineType,
    ForecastSensitivity,
    ForecastTargetDirection,
} from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import {
    clampHorizon,
    forecastTargetDateError,
    forecastErrorThresholdError,
    forecastTargetValueError,
    maxHorizonForInterval,
} from 'products/alerts/frontend/logic/forecastReach'

/** Labels the horizon input. Keyed by the insight's interval, since that is what the horizon counts. */
const HORIZON_UNIT: Partial<Record<IntervalType, string>> = {
    minute: 'minutes',
    hour: 'hours',
    day: 'days',
    week: 'weeks',
    month: 'months',
}

/** Default lookahead window for a "predicted to breach" forecast, in calculation-interval units. */
const DEFAULT_HORIZON = 7
/** Default band width, matching the "Wider" option that fires only on clear deviations. */
const DEFAULT_INTERVAL_WIDTH = 0.95
/** Fire as soon as a value leaves the range, which is how band alerts behaved before the control existed. */
const DEFAULT_SCORE_THRESHOLD = 0
/** One full band half-width past the edge. Above roughly two, a well-calibrated band never fires. */
const FAR_PAST_SCORE_THRESHOLD = 1
/** Default distance for percentage mode, as a fraction. */
const DEFAULT_ERROR_THRESHOLD_PCT = 0.2
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

/** The threshold inputs are stored as fractions and shown as percentages, so a user types 20 rather
 *  than 0.2. Kept together so the two conversions cannot drift apart. */
function toPercent(fraction: number | null | undefined): number | undefined {
    return fraction == null ? undefined : Math.round(fraction * 1000) / 10
}

function fromPercent(percent: number | null | undefined): number | undefined {
    return percent == null ? undefined : percent / 100
}

/** Seeds the threshold a mode reads and drops the ones it does not, so a value left over from
 *  another mode cannot reach the evaluator unseen. */
export function withErrorModeDefaults(config: ForecastConfig, errorMode: ForecastErrorMode): ForecastConfig {
    return {
        ...config,
        error_mode: errorMode,
        error_threshold_pct:
            errorMode === ForecastErrorMode.RELATIVE
                ? (config.error_threshold_pct ?? DEFAULT_ERROR_THRESHOLD_PCT)
                : undefined,
        error_threshold_abs: errorMode === ForecastErrorMode.ABSOLUTE ? config.error_threshold_abs : undefined,
        score_threshold: errorMode === ForecastErrorMode.PREDICTION_INTERVAL ? config.score_threshold : undefined,
    }
}

/** Seeds the fields a condition needs when the user switches to it, so a target starts with a date
 *  already in range rather than an empty control the save path would reject. */
export function withConditionDefaults(config: ForecastConfig, condition: ForecastConditionType): ForecastConfig {
    // Each condition reads a different subset, and the unread fields still reach the engine. A
    // horizon left over from a predicted breach inflates the query window for a condition that
    // forecasts one interval, and a band width left over from an expected-range alert silently
    // moves when a predicted breach fires, with no control on screen showing it.
    const next: ForecastConfig = {
        ...config,
        condition,
        horizon: condition === ForecastConditionType.FUTURE_BREACH ? config.horizon : undefined,
        interval_width:
            condition === ForecastConditionType.BAND_DEVIATION ? config.interval_width : DEFAULT_INTERVAL_WIDTH,
        // These four only mean anything to an expected-range alert. Left behind, they would reach the
        // evaluator with no control on screen showing them.
        ...(condition === ForecastConditionType.BAND_DEVIATION
            ? {}
            : {
                  direction: undefined,
                  error_mode: undefined,
                  error_threshold_pct: undefined,
                  error_threshold_abs: undefined,
                  score_threshold: undefined,
              }),
    }
    if (condition !== ForecastConditionType.TARGET_BY_DATE) {
        return next
    }
    return {
        ...next,
        target_direction: config.target_direction ?? ForecastTargetDirection.AT_LEAST,
        target_date: config.target_date ?? dayjs().add(DEFAULT_TARGET_DAYS, 'day').format('YYYY-MM-DD'),
    }
}

export function getDefaultForecastConfig(insightInterval?: IntervalType | null): ForecastConfig {
    return clampHorizon(
        {
            type: 'ForecastConfig',
            engine: ForecastEngineType.PROPHET,
            condition: ForecastConditionType.FUTURE_BREACH,
            horizon: DEFAULT_HORIZON,
            interval_width: DEFAULT_INTERVAL_WIDTH,
        },
        insightInterval
    )
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
    /** The insight's grouping interval. The horizon counts insight buckets, not check cadence. */
    insightInterval: IntervalType | null | undefined
}

export function ForecastSelector({ value, onChange, insightInterval }: ForecastSelectorProps): JSX.Element {
    const config = value ?? getDefaultForecastConfig(insightInterval)
    const unit = HORIZON_UNIT[insightInterval ?? 'day'] ?? 'intervals'
    // The backend caps reach as a duration, so this ceiling moves with the insight's interval.
    const maxHorizon = maxHorizonForInterval(insightInterval)
    const targetDateError = forecastTargetDateError(config.target_date, dayjs())
    // The save blocks on this, so the field it names has to show it.
    const targetValueError =
        config.condition === ForecastConditionType.TARGET_BY_DATE ? forecastTargetValueError(config.target) : null
    const errorMode = config.error_mode ?? ForecastErrorMode.PREDICTION_INTERVAL
    // The save blocks on this, so the field it names has to show it.
    const thresholdError =
        config.condition === ForecastConditionType.BAND_DEVIATION ? forecastErrorThresholdError(config) : null
    // A predicted breach has a threshold to cross, not a target to miss.
    const missesOrCrosses = config.condition === ForecastConditionType.FUTURE_BREACH ? 'crosses it' : 'misses'
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
                        label: 'Off track for a target',
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
                        aria-label="Target value"
                        status={targetValueError ? 'danger' : undefined}
                        value={config.target ?? undefined}
                        onChange={(target) => onChange({ ...config, target: target ?? undefined })}
                    />
                    <span className="whitespace-nowrap">on</span>
                    <LemonCalendarSelectInput
                        selectionPeriod="upcoming"
                        buttonProps={{ fullWidth: false, 'data-attr': 'alertForm-forecast-target-date' }}
                        value={config.target_date ? dayjs(config.target_date) : null}
                        onChange={(d) => onChange({ ...config, target_date: d ? d.format('YYYY-MM-DD') : undefined })}
                    />
                    {targetValueError || targetDateError ? (
                        <div className="w-full text-danger text-xs" data-attr="alertForm-forecast-target-date-error">
                            {targetValueError ?? targetDateError}
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
                        aria-label="Forecast horizon"
                        min={1}
                        max={maxHorizon}
                        value={config.horizon ?? DEFAULT_HORIZON}
                        onChange={(horizon) =>
                            onChange({
                                ...config,
                                horizon: Math.min(Math.max(horizon ?? DEFAULT_HORIZON, 1), maxHorizon),
                            })
                        }
                    />
                    <span>{unit}</span>
                    <SettingHelp text="How far ahead to look. A shorter window is more reliable, a longer one gives you more time to react." />
                </div>
            )}
            {config.condition === ForecastConditionType.BAND_DEVIATION && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <div className="flex items-center gap-2">
                        <span className="text-secondary whitespace-nowrap">Measure by</span>
                        <SettingHelp text="How to decide a value is off. The expected range adapts to how noisy the metric already is. A percentage or a fixed amount is a number you set yourself." />
                        <LemonSelect
                            size="small"
                            data-attr="alertForm-forecast-error-mode"
                            value={errorMode}
                            onChange={(error_mode) => onChange(withErrorModeDefaults(config, error_mode))}
                            options={[
                                { label: 'Expected range', value: ForecastErrorMode.PREDICTION_INTERVAL },
                                { label: 'Percentage off', value: ForecastErrorMode.RELATIVE },
                                { label: 'Fixed amount off', value: ForecastErrorMode.ABSOLUTE },
                            ]}
                        />
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-secondary whitespace-nowrap">Alert on</span>
                        <SettingHelp text="Which way a value has to move to matter. Drops for things you want high like revenue, spikes for things you want low like errors." />
                        <LemonSelect
                            size="small"
                            data-attr="alertForm-forecast-direction"
                            value={config.direction ?? ForecastDirection.BOTH}
                            onChange={(direction) => onChange({ ...config, direction })}
                            options={[
                                { label: 'any move', value: ForecastDirection.BOTH },
                                { label: 'spikes only', value: ForecastDirection.ABOVE },
                                { label: 'drops only', value: ForecastDirection.BELOW },
                            ]}
                        />
                    </div>
                    {errorMode === ForecastErrorMode.RELATIVE && (
                        <div className="flex items-center gap-2">
                            <LemonInput
                                type="number"
                                className="w-20"
                                data-attr="alertForm-forecast-error-threshold-pct"
                                aria-label="Percentage off the forecast"
                                status={thresholdError ? 'danger' : undefined}
                                min={1}
                                suffix={<span>%</span>}
                                value={toPercent(config.error_threshold_pct)}
                                onChange={(pct) => onChange({ ...config, error_threshold_pct: fromPercent(pct) })}
                            />
                            <span className="whitespace-nowrap">off the forecast</span>
                        </div>
                    )}
                    {errorMode === ForecastErrorMode.ABSOLUTE && (
                        <div className="flex items-center gap-2">
                            <LemonInput
                                type="number"
                                className="w-24"
                                data-attr="alertForm-forecast-error-threshold-abs"
                                aria-label="Amount off the forecast"
                                status={thresholdError ? 'danger' : undefined}
                                value={config.error_threshold_abs ?? undefined}
                                onChange={(error_threshold_abs) =>
                                    onChange({ ...config, error_threshold_abs: error_threshold_abs ?? undefined })
                                }
                            />
                            <span className="whitespace-nowrap">off the forecast</span>
                        </div>
                    )}
                    {thresholdError ? (
                        <div className="w-full text-danger text-xs" data-attr="alertForm-forecast-threshold-error">
                            {thresholdError}
                        </div>
                    ) : null}
                </div>
            )}
            {/* The label and its control wrap as one unit, so the label never strands on the row above. */}
            {config.condition === ForecastConditionType.BAND_DEVIATION &&
                errorMode === ForecastErrorMode.PREDICTION_INTERVAL && (
                    <div className="flex items-center gap-2">
                        <span className="text-secondary whitespace-nowrap">Expected range</span>
                        <SettingHelp text="How far from normal counts as unusual. Narrower catches smaller deviations and fires more often." />
                        <LemonSegmentedButton
                            size="small"
                            value={config.interval_width ?? DEFAULT_INTERVAL_WIDTH}
                            onChange={(interval_width) => onChange({ ...config, interval_width })}
                            options={[
                                {
                                    value: 0.8,
                                    label: 'Narrower',
                                    'data-attr': 'alertForm-forecast-interval-width-narrower',
                                    tooltip: 'More sensitive. Fires on smaller deviations, with more noise.',
                                },
                                {
                                    value: DEFAULT_INTERVAL_WIDTH,
                                    label: 'Wider',
                                    'data-attr': 'alertForm-forecast-interval-width-wider',
                                    tooltip: 'Fires only on clear deviations.',
                                },
                            ]}
                        />
                        <SettingHelp text="How far past the range counts. Higher fires less without changing what counts as normal." />
                        <LemonSegmentedButton
                            size="small"
                            value={config.score_threshold ?? DEFAULT_SCORE_THRESHOLD}
                            onChange={(score_threshold) => onChange({ ...config, score_threshold })}
                            options={[
                                {
                                    value: DEFAULT_SCORE_THRESHOLD,
                                    label: 'Just past it',
                                    'data-attr': 'alertForm-forecast-score-threshold-edge',
                                    tooltip: 'Fires as soon as a value leaves the range.',
                                },
                                {
                                    value: FAR_PAST_SCORE_THRESHOLD,
                                    label: 'Well past it',
                                    'data-attr': 'alertForm-forecast-score-threshold-far',
                                    tooltip: 'Waits until a value is clearly outside, so borderline points stay quiet.',
                                },
                            ]}
                        />
                    </div>
                )}
            {config.condition !== ForecastConditionType.BAND_DEVIATION && (
                /* The band width does not decide when these two fire; which line they read does. */
                <div className="flex items-center gap-2">
                    <span className="text-secondary whitespace-nowrap">Alert when</span>
                    <SettingHelp text="How certain to be before alerting. The best case waits until the outcome can no longer be avoided, so it fires less often." />
                    <LemonSegmentedButton
                        size="small"
                        value={config.sensitivity ?? defaultSensitivity(config.condition)}
                        onChange={(sensitivity) => onChange({ ...config, sensitivity })}
                        options={[
                            {
                                value: ForecastSensitivity.FORECAST,
                                label: `The forecast ${missesOrCrosses}`,
                                'data-attr': 'alertForm-forecast-sensitivity-forecast',
                                tooltip: 'Warns earlier, and can change its mind while the forecast is uncertain.',
                            },
                            {
                                value: ForecastSensitivity.BEST_CASE,
                                label: `Even the best case ${missesOrCrosses}`,
                                'data-attr': 'alertForm-forecast-sensitivity-best-case',
                                tooltip: 'Quieter. Waits until the outcome is no longer avoidable.',
                            },
                        ]}
                    />
                </div>
            )}
        </div>
    )
}
