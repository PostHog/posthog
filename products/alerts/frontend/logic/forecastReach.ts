import { dayjs } from 'lib/dayjs'
import { getExcludedDaysOfWeek } from 'scenes/insights/filters/InsightDateFilter/daysOfWeekFilterUtils'

import { AlertCalculationInterval, DateRange } from '~/queries/schema/schema-general'
import { ChartDisplayType, IntervalType } from '~/types'

import {
    getDefaultSimulationRange,
    getSimulationRangeOptions,
    INSIGHT_INTERVAL_DURATION_MINUTES,
} from './alertIntervalHelpers'

export const MAX_FORECAST_REACH_DAYS = 92
export const MAX_FORECAST_OUTPUT_POINTS = 250

const MINUTES_PER_DAY = 60 * 24
const SUPPORTED_FORECAST_INTERVALS: ReadonlySet<IntervalType> = new Set(['hour', 'day', 'week', 'month'])

export function intervalSupportsForecast(interval: IntervalType | null | undefined): boolean {
    return interval == null || SUPPORTED_FORECAST_INTERVALS.has(interval)
}

/** Mirrors `validate_forecast_days_of_week` in products/alerts/backend/forecasting/engine.py: a
 * daily insight that leaves days out charts a history with gaps, and the forecast fills them back
 * in from a weekly shape the history never constrained. Coarser intervals keep every bucket. */
export function dateRangeSupportsForecast(
    dateRange: DateRange | null | undefined,
    interval: IntervalType | null | undefined
): boolean {
    if (interval != null && interval !== 'day') {
        return true
    }
    return getExcludedDaysOfWeek(dateRange).length === 0
}

/** Both displays keep the insight's interval, so they read as a time series, but neither returns
 * one to fit: the box plot returns a distribution per bucket, and the slope keeps only the first
 * and last bucket. */
const UNFORECASTABLE_DISPLAYS: ReadonlySet<ChartDisplayType> = new Set([
    ChartDisplayType.ActionsLineGraphCumulative,
    ChartDisplayType.BoxPlot,
    ChartDisplayType.SlopeGraph,
])

export function displaySupportsForecast(display: ChartDisplayType | null | undefined): boolean {
    return display == null || !UNFORECASTABLE_DISPLAYS.has(display)
}

export function targetByDateSupportsForecast(interval: IntervalType | null | undefined): boolean {
    return interval !== 'hour'
}

/** Days per interval as the backend counts them, from `_INTERVAL_DAYS` in
 * products/alerts/backend/forecasting/engine.py. A month is 30.4 days there, so the cap has to use
 * the same lengths and round down, or the backend refuses the horizon this editor offers. */
const FORECAST_INTERVAL_DAYS: Partial<Record<IntervalType, number>> = {
    hour: 1 / 24,
    day: 1,
    week: 7,
    month: 30.4,
}

export function maxHorizonForInterval(interval: IntervalType | null | undefined): number {
    const days = FORECAST_INTERVAL_DAYS[interval ?? 'day'] ?? 1
    return Math.min(MAX_FORECAST_OUTPUT_POINTS, Math.floor(MAX_FORECAST_REACH_DAYS / days))
}

/** The furthest a target date can sit and still pass `forecastTargetReachError`: 92 days of reach,
 * and no more than 250 forecast points at the insight's interval. The point cap binds first on an
 * hourly insight, where 92 days would need 2208 points. */
export function maxTargetDaysForInterval(interval: IntervalType | null | undefined): number {
    const intervalMinutes = INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day']
    const byPoints = Math.floor((MAX_FORECAST_OUTPUT_POINTS * intervalMinutes) / MINUTES_PER_DAY)
    return Math.max(1, Math.min(MAX_FORECAST_REACH_DAYS, byPoints))
}

export function clampHorizon<T extends { horizon?: number | null }>(
    config: T,
    interval: IntervalType | null | undefined
): T {
    if (config.horizon == null) {
        return config
    }
    // The backend takes whole intervals, so round a fractional entry here instead of failing the request.
    const clamped = Math.round(Math.min(Math.max(config.horizon, 1), maxHorizonForInterval(interval)))
    return clamped === config.horizon ? config : { ...config, horizon: clamped }
}

export function forecastTargetValueError(target: number | null | undefined): string | null {
    return target != null && Number.isFinite(target) ? null : 'Enter a target value'
}

export function forecastTargetDateError(
    targetDate: string | undefined,
    today: dayjs.Dayjs,
    interval?: IntervalType | null
): string | null {
    if (!targetDate) {
        return 'Choose a target date'
    }
    if (dayjs(targetDate).startOf('day').diff(today.startOf('day'), 'day') <= 0) {
        return 'The target date must be in the future.'
    }
    return forecastTargetReachError(targetDate, today, interval)
}

/** How far a target date reaches. Split out because a saved date keeps its past-date pass, the way
 * the server does, while these limits still apply to it: both depend on the insight's interval,
 * which can be regrouped to a finer bucket after the alert was saved. */
export function forecastTargetReachError(
    targetDate: string | undefined,
    today: dayjs.Dayjs,
    interval?: IntervalType | null
): string | null {
    if (!targetDate) {
        return null
    }
    const days = dayjs(targetDate).startOf('day').diff(today.startOf('day'), 'day')
    if (days > MAX_FORECAST_REACH_DAYS) {
        return 'A forecast target must be within 92 days. Move the date closer, or use quarterly milestones.'
    }
    const intervalMinutes = INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day']
    const outputPoints = Math.ceil((days * MINUTES_PER_DAY) / intervalMinutes)
    if (outputPoints > MAX_FORECAST_OUTPUT_POINTS) {
        return `This interval needs more than ${MAX_FORECAST_OUTPUT_POINTS} forecast points. Use a coarser insight interval.`
    }
    return null
}

export function minForecastPoints(interval: IntervalType | null | undefined): number {
    return interval === 'hour' ? 48 : 14
}

export function pointsInSimulationRange(range: string, interval: IntervalType | null | undefined): number {
    const match = /^-(\d+)([mhdwM])$/.exec(range)
    if (!match) {
        return Number.POSITIVE_INFINITY
    }
    const [, amount, unit] = match
    const rangeMinutes = Number(amount) * (UNIT_MINUTES[unit] ?? 1)
    return Math.floor(rangeMinutes / INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day'])
}

/** PostHog's relative-date units: lowercase `m` is months, uppercase `M` is minutes.
 * See `get_delta_mapping_for` in posthog/utils.py. */
const UNIT_MINUTES: Record<string, number> = {
    M: 1,
    h: 60,
    d: MINUTES_PER_DAY,
    w: 7 * MINUTES_PER_DAY,
    m: 30 * MINUTES_PER_DAY,
}

export function usableSimulationRanges<T extends { value: string }>(
    options: T[],
    interval: IntervalType | null | undefined
): T[] {
    const required = minForecastPoints(interval)
    const usable = options.filter((option) => pointsInSimulationRange(option.value, interval) >= required)
    return usable.length > 0 ? usable : options.slice(-1)
}

/** The history range a forecast preview runs over. The stored range can sit outside the offered
 * list, because the cadence changed under it or because it is too short for the insight's interval.
 * The control and the request both resolve it here, so the chart cannot answer a different window
 * from the one on screen. */
export function resolveForecastSimulationRange(
    storedRange: string | null,
    cadence: AlertCalculationInterval,
    insightInterval: IntervalType | null | undefined
): string {
    const options = usableSimulationRanges(getSimulationRangeOptions(cadence), insightInterval)
    const selected = storedRange ?? getDefaultSimulationRange(cadence)
    return options.some((option) => option.value === selected) ? selected : options[0].value
}
