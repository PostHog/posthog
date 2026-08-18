import { dayjs } from 'lib/dayjs'

import { IntervalType } from '~/types'

import { INSIGHT_INTERVAL_DURATION_MINUTES } from './alertIntervalHelpers'

/** Kept in step with MAX_FORECAST_REACH_DAYS in products/alerts/backend/forecasting/engine.py,
 *  which is the source of truth. Same name in both languages so one grep finds both halves. */
export const MAX_FORECAST_REACH_DAYS = 183

const MINUTES_PER_DAY = 60 * 24

/** How many intervals a forecast may look ahead.
 *
 * Keyed by the INSIGHT's interval, not the alert's check cadence. The horizon counts insight
 * buckets, because that is what the engine forecasts, so a weekly insight checked daily still
 * gets a ceiling in weeks. */
export function maxHorizonForInterval(interval: IntervalType | null | undefined): number {
    const minutes = INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day']
    return Math.max(1, Math.floor((MAX_FORECAST_REACH_DAYS * MINUTES_PER_DAY) / minutes))
}

/** Why a target date cannot be forecast, or null when it can. Mirrors horizon_for_target_date in
 *  products/alerts/backend/forecasting/engine.py so the editor and the server agree on the wording. */
export function forecastTargetDateError(targetDate: string | undefined, today: dayjs.Dayjs): string | null {
    if (!targetDate) {
        return null
    }
    const days = dayjs(targetDate).startOf('day').diff(today.startOf('day'), 'day')
    if (days <= 0) {
        return 'The target date must be in the future.'
    }
    if (days > MAX_FORECAST_REACH_DAYS) {
        return 'A forecast target must be within 6 months. Move the date closer, or use an insight with a coarser interval.'
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
    const match = /^-(\d+)([mhdwM])$/.exec(range)
    if (!match) {
        return Number.POSITIVE_INFINITY
    }
    const [, amount, unit] = match
    const rangeMinutes = Number(amount) * (UNIT_MINUTES[unit] ?? 1)
    return Math.floor(rangeMinutes / INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day'])
}

const UNIT_MINUTES: Record<string, number> = {
    m: 1,
    h: 60,
    d: 60 * 24,
    w: 60 * 24 * 7,
    M: 60 * 24 * 30,
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
