import { dayjs } from 'lib/dayjs'

import { ForecastErrorMode } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { INSIGHT_INTERVAL_DURATION_MINUTES } from './alertIntervalHelpers'

/** Kept in step with MAX_FORECAST_REACH_DAYS in products/alerts/backend/forecasting/engine.py,
 *  which is the source of truth. Same name in both languages so one grep finds both halves. */
export const MAX_FORECAST_REACH_DAYS = 183

const MINUTES_PER_DAY = 60 * 24

/** Mirrors SUPPORTED_FORECAST_INTERVALS in products/alerts/backend/forecasting/engine.py. Prophet
 *  needs a seasonal cycle it can see, which the other insight intervals do not give it. */
const SUPPORTED_FORECAST_INTERVALS: ReadonlySet<IntervalType> = new Set(['hour', 'day', 'week', 'month'])

/** A null interval means the insight uses the daily default, which is supported. */
export function intervalSupportsForecast(interval: IntervalType | null | undefined): boolean {
    return interval == null || SUPPORTED_FORECAST_INTERVALS.has(interval)
}

/** How many intervals a forecast may look ahead.
 *
 * Keyed by the INSIGHT's interval, not the alert's check cadence. The horizon counts insight
 * buckets, because that is what the engine forecasts, so a weekly insight checked daily still
 * gets a ceiling in weeks. */
export function maxHorizonForInterval(interval: IntervalType | null | undefined): number {
    const minutes = INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day']
    return Math.max(1, Math.floor((MAX_FORECAST_REACH_DAYS * MINUTES_PER_DAY) / minutes))
}

/** Pull a horizon inside the reach cap for an interval. Applied wherever a forecast config is
 *  written, so the number on screen is always the number that gets submitted. */
export function clampHorizon<T extends { horizon?: number | null }>(
    config: T,
    interval: IntervalType | null | undefined
): T {
    if (config.horizon == null) {
        return config
    }
    const clamped = Math.min(Math.max(config.horizon, 1), maxHorizonForInterval(interval))
    return clamped === config.horizon ? config : { ...config, horizon: clamped }
}

/** Why a target value is unusable, or null when it is fine. Shared so the field that blocks the
 *  save is the field that gets marked. Direction-neutral: an at_most target is a ceiling to stay
 *  under, not a number to reach. */
export function forecastTargetValueError(target: number | null | undefined): string | null {
    return target != null && Number.isFinite(target) ? null : 'Enter a target value'
}

/** Why a deviation threshold is unusable, or null when it is fine. Shared so the field that blocks
 *  the save is the field that gets marked. */
export function forecastErrorThresholdError(config: {
    error_mode?: ForecastErrorMode | null
    error_threshold_pct?: number | null
    error_threshold_abs?: number | null
}): string | null {
    if (config.error_mode === ForecastErrorMode.RELATIVE) {
        const pct = config.error_threshold_pct
        return pct != null && Number.isFinite(pct) && pct > 0 ? null : 'Enter a percentage above zero'
    }
    if (config.error_mode === ForecastErrorMode.ABSOLUTE) {
        const abs = config.error_threshold_abs
        return abs != null && Number.isFinite(abs) && abs > 0 ? null : 'Enter an amount above zero'
    }
    return null
}

/** Why a target date cannot be forecast, or null when it can. Reach is measured from today and does
 *  not vary by interval: save is the only place that enforces the cap, and evaluation derives its own
 *  horizon from the last completed bucket without re-checking it. Mirrors horizon_for_target_date in
 *  products/alerts/backend/forecasting/engine.py, including the wording. */
export function forecastTargetDateError(targetDate: string | undefined, today: dayjs.Dayjs): string | null {
    if (!targetDate) {
        return null
    }
    const days = dayjs(targetDate).startOf('day').diff(today.startOf('day'), 'day')
    if (days <= 0) {
        return 'The target date must be in the future.'
    }
    if (days > MAX_FORECAST_REACH_DAYS) {
        return 'A forecast target must be within 6 months. Move the date closer.'
    }
    return null
}

/** Mirrors min_forecast_points in products/alerts/backend/forecasting/engine.py. Roughly two
 *  seasonal cycles: hourly needs two days to see a daily cycle, everything else two weeks. */
export function minForecastPoints(interval: IntervalType | null | undefined, condition: string | undefined): number {
    const base = interval === 'hour' ? 48 : 14
    // Band deviation holds the latest point out as the actual, so it fits on one fewer than it gets.
    return condition === 'band_deviation' ? base + 1 : base
}

/** How many insight buckets a simulation range covers. The range is a duration and the buckets are
 *  the insight's, so "-30d" is 30 points daily but about 4 weekly. */
export function pointsInSimulationRange(range: string, interval: IntervalType | null | undefined): number {
    const match = /^-(\d+)([hdwm])$/.exec(range)
    if (!match) {
        return Number.POSITIVE_INFINITY
    }
    const [, amount, unit] = match
    const rangeMinutes = Number(amount) * (UNIT_MINUTES[unit] ?? 1)
    return Math.floor(rangeMinutes / INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day'])
}

// PostHog relative dates use `m` for months, not minutes, which is what the alert range options and
// _date_range_override_for_detector both emit.
const UNIT_MINUTES: Record<string, number> = {
    h: 60,
    d: 60 * 24,
    w: 60 * 24 * 7,
    m: 60 * 24 * 30,
}

/** Simulation ranges that can actually produce a forecast, so the picker cannot offer one the
 *  backend will reject with "Not enough history". Falls back to the longest if none qualify. */
export function usableSimulationRanges<T extends { value: string }>(
    options: T[],
    interval: IntervalType | null | undefined,
    condition: string | undefined
): T[] {
    const required = minForecastPoints(interval, condition)
    const usable = options.filter((o) => pointsInSimulationRange(o.value, interval) >= required)
    return usable.length > 0 ? usable : options.slice(-1)
}
