import { dayjs } from 'lib/dayjs'

import { ForecastErrorMode } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { INSIGHT_INTERVAL_DURATION_MINUTES } from './alertIntervalHelpers'

export const MAX_FORECAST_REACH_DAYS = 183

const MINUTES_PER_DAY = 60 * 24

const SUPPORTED_FORECAST_INTERVALS: ReadonlySet<IntervalType> = new Set(['hour', 'day', 'week', 'month'])

export function intervalSupportsForecast(interval: IntervalType | null | undefined): boolean {
    return interval == null || SUPPORTED_FORECAST_INTERVALS.has(interval)
}

export function maxHorizonForInterval(interval: IntervalType | null | undefined): number {
    const minutes = INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day']
    return Math.max(1, Math.floor((MAX_FORECAST_REACH_DAYS * MINUTES_PER_DAY) / minutes))
}

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

export function forecastTargetValueError(target: number | null | undefined): string | null {
    return target != null && Number.isFinite(target) ? null : 'Enter a target value'
}

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

export function minForecastPoints(interval: IntervalType | null | undefined, condition: string | undefined): number {
    const base = interval === 'hour' ? 48 : 14
    return condition === 'band_deviation' ? base + 1 : base
}

export function pointsInSimulationRange(range: string, interval: IntervalType | null | undefined): number {
    const match = /^-(\d+)([hdwm])$/.exec(range)
    if (!match) {
        return Number.POSITIVE_INFINITY
    }
    const [, amount, unit] = match
    const rangeMinutes = Number(amount) * (UNIT_MINUTES[unit] ?? 1)
    return Math.floor(rangeMinutes / INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day'])
}

const UNIT_MINUTES: Record<string, number> = {
    h: 60,
    d: 60 * 24,
    w: 60 * 24 * 7,
    m: 60 * 24 * 30,
}

export function usableSimulationRanges<T extends { value: string }>(
    options: T[],
    interval: IntervalType | null | undefined,
    condition: string | undefined
): T[] {
    const required = minForecastPoints(interval, condition)
    const usable = options.filter((o) => pointsInSimulationRange(o.value, interval) >= required)
    return usable.length > 0 ? usable : options.slice(-1)
}
