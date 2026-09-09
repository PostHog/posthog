import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonInput, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { dayjs, dayjsNowInTimezone } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import {
    ForecastConditionType,
    ForecastConfig,
    ForecastEngineType,
    ForecastTargetDirection,
    FutureBreachForecastConfig,
} from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import {
    clampHorizon,
    DEFAULT_FORECAST_HORIZON,
    defaultHorizonForInterval,
    forecastTargetIntervalError,
    forecastTargetValueError,
    maxHorizonForInterval,
    maxTargetDaysForInterval,
} from 'products/alerts/frontend/logic/forecastReach'

const HORIZON_UNIT: Partial<Record<IntervalType, string>> = {
    hour: 'hours',
    day: 'days',
    week: 'weeks',
    month: 'months',
}

const DEFAULT_TARGET_DAYS = 90

/** Merges a horizon the user typed. An emptied number input reports NaN, which `??` does not
 *  catch, so a cleared field would store NaN, serialize to null, and then evaluate as the
 *  backend's own default. Keep the horizon already set until a real number arrives. */
export function withEnteredHorizon(
    config: FutureBreachForecastConfig,
    entered: number | null | undefined,
    insightInterval?: IntervalType | null
): ForecastConfig {
    const horizon = entered != null && Number.isFinite(entered) ? entered : (config.horizon ?? DEFAULT_FORECAST_HORIZON)
    return clampHorizon({ ...config, horizon }, insightInterval)
}

export function withConditionDefaults(
    config: ForecastConfig,
    condition: ForecastConditionType,
    today: dayjs.Dayjs = dayjs(),
    insightInterval?: IntervalType | null
): ForecastConfig {
    if (condition === ForecastConditionType.FUTURE_BREACH) {
        const nextConfig: FutureBreachForecastConfig = {
            type: 'ForecastConfig',
            engine: config.engine,
            condition,
            horizon:
                config.condition === ForecastConditionType.FUTURE_BREACH
                    ? (config.horizon ?? DEFAULT_FORECAST_HORIZON)
                    : DEFAULT_FORECAST_HORIZON,
        }
        return clampHorizon(nextConfig, insightInterval)
    }
    return {
        type: 'ForecastConfig',
        engine: config.engine,
        condition,
        target: config.condition === ForecastConditionType.TARGET_BY_DATE ? config.target : Number.NaN,
        target_direction:
            config.condition === ForecastConditionType.TARGET_BY_DATE
                ? config.target_direction
                : ForecastTargetDirection.AT_LEAST,
        target_date:
            config.condition === ForecastConditionType.TARGET_BY_DATE
                ? config.target_date
                : // A fine insight interval reaches less far, so seed the nearest date the interval
                  // allows instead of a fixed quarter that opens the path in an error state.
                  today
                      .add(Math.min(DEFAULT_TARGET_DAYS, maxTargetDaysForInterval(insightInterval)), 'day')
                      .format('YYYY-MM-DD'),
    }
}

export function getDefaultForecastConfig(insightInterval?: IntervalType | null): ForecastConfig {
    const config: FutureBreachForecastConfig = {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: DEFAULT_FORECAST_HORIZON,
    }
    return clampHorizon(config, insightInterval)
}

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
    insightInterval: IntervalType | null | undefined
    projectTimezone?: string
    disabledReason?: string
    /** The form's message about the target date, or null. The form knows the date the alert was
     * saved with, which an expired target keeps until it is changed, so it is the only place that
     * can tell an unreachable new date from a passed one the server still accepts. */
    targetDateError: string | null
}

export function ForecastSelector({
    value,
    onChange,
    insightInterval,
    projectTimezone,
    disabledReason,
    targetDateError,
}: ForecastSelectorProps): JSX.Element {
    const config = value ?? getDefaultForecastConfig(insightInterval)
    const today = projectTimezone ? dayjsNowInTimezone(projectTimezone) : dayjs()
    const unit = HORIZON_UNIT[insightInterval ?? 'day'] ?? 'intervals'
    const maxHorizon = maxHorizonForInterval(insightInterval)

    return (
        <div className="space-y-3">
            <div className="flex items-center gap-1.5 text-sm font-medium">
                <span>Forecast path</span>
                <SettingHelp text="Choose whether to watch an operational limit or a dated business target." />
            </div>
            <LemonRadio
                radioPosition="top"
                value={config.condition}
                onChange={(condition: ForecastConditionType) =>
                    onChange(withConditionDefaults(config, condition, today, insightInterval))
                }
                options={[
                    {
                        value: ForecastConditionType.FUTURE_BREACH,
                        label: 'Upcoming threshold breach',
                        description:
                            'Alert if the point forecast crosses a less-than or more-than threshold soon, or if the latest value already crosses it.',
                        'data-attr': 'alertForm-forecast-condition-future-breach',
                        disabledReason,
                    },
                    {
                        value: ForecastConditionType.TARGET_BY_DATE,
                        label: 'Target by date',
                        description: 'Alert if the value forecast for a chosen date is on the wrong side of a target.',
                        'data-attr': 'alertForm-forecast-condition-target-by-date',
                        disabledReason: disabledReason ?? forecastTargetIntervalError(insightInterval) ?? undefined,
                    },
                ]}
            />

            {config.condition === ForecastConditionType.FUTURE_BREACH ? (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="whitespace-nowrap">Look ahead</span>
                    <LemonInput
                        type="number"
                        className="w-20"
                        data-attr="alertForm-forecast-horizon"
                        aria-label="Forecast horizon"
                        min={1}
                        max={maxHorizon}
                        value={config.horizon ?? defaultHorizonForInterval(insightInterval)}
                        disabledReason={disabledReason}
                        onChange={(horizon) => onChange(withEnteredHorizon(config, horizon, insightInterval))}
                    />
                    <span>{unit}</span>
                    <SettingHelp text="Forecasts are limited to 92 days and 250 output points. Shorter horizons are generally more stable." />
                </div>
            ) : (
                <TargetByDateFields
                    config={config}
                    projectTimezone={projectTimezone}
                    disabledReason={disabledReason}
                    targetDateError={targetDateError}
                    onChange={onChange}
                />
            )}
        </div>
    )
}

function TargetByDateFields({
    config,
    projectTimezone,
    disabledReason,
    targetDateError,
    onChange,
}: {
    config: Extract<ForecastConfig, { condition: ForecastConditionType.TARGET_BY_DATE }>
    projectTimezone?: string
    disabledReason?: string
    targetDateError: string | null
    onChange: (config: ForecastConfig) => void
}): JSX.Element {
    const targetValueError = forecastTargetValueError(config.target)
    // The server accepts every ISO date form, week dates included, and stores what it was sent.
    // dayjs reads none of the week forms and prints "Invalid Date" for them, so hand the calendar
    // nothing and show the stored date until the picker replaces it.
    const storedTargetDate = config.target_date ? dayjs(config.target_date) : null
    const pickedTargetDate = storedTargetDate?.isValid() ? storedTargetDate : null

    return (
        <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
                <span className="whitespace-nowrap">The value should be</span>
                <LemonSelect
                    data-attr="alertForm-forecast-target-direction"
                    value={config.target_direction}
                    disabledReason={disabledReason}
                    onChange={(target_direction) => onChange({ ...config, target_direction })}
                    options={[
                        { label: 'at least', value: ForecastTargetDirection.AT_LEAST },
                        { label: 'at most', value: ForecastTargetDirection.AT_MOST },
                    ]}
                />
                <LemonInput
                    type="number"
                    // A target can be a rate or an average. The native step defaults to 1, so a
                    // decimal fails the browser's own validation and blocks the save.
                    step="any"
                    className="w-24"
                    data-attr="alertForm-forecast-target"
                    aria-label="Target value"
                    status={targetValueError ? 'danger' : undefined}
                    value={Number.isFinite(config.target) ? config.target : undefined}
                    disabledReason={disabledReason}
                    onChange={(target) => onChange({ ...config, target: target ?? Number.NaN })}
                />
                <span className="whitespace-nowrap">on</span>
                <LemonCalendarSelectInput
                    selectionPeriod="upcoming"
                    // Without the project timezone the calendar draws its past/future boundary from
                    // the browser, so it can offer a date the project-timezone validation rejects.
                    selectionPeriodTimezone={projectTimezone}
                    buttonProps={{
                        fullWidth: false,
                        'data-attr': 'alertForm-forecast-target-date',
                        disabledReason,
                    }}
                    value={pickedTargetDate}
                    placeholder={config.target_date || undefined}
                    onChange={(date) =>
                        onChange({
                            ...config,
                            target_date: date ? date.format('YYYY-MM-DD') : '',
                        })
                    }
                />
            </div>
            {targetValueError || targetDateError ? (
                <div className="text-danger text-xs" data-attr="alertForm-forecast-target-error">
                    {targetValueError ?? targetDateError}
                </div>
            ) : null}
            <LemonBanner type="info">
                This checks the value in the target date's insight bucket, not a total accumulated by then. Keep targets
                within 92 days; use quarterly milestones for annual goals. The alert expires silently when the target
                date arrives.
            </LemonBanner>
        </div>
    )
}
