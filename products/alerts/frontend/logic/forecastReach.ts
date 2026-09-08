import { dayjs } from 'lib/dayjs'

import { ChartDisplayType, IntervalType } from '~/types'

import { INSIGHT_INTERVAL_DURATION_MINUTES } from './alertIntervalHelpers'

export const MAX_FORECAST_REACH_DAYS = 92
export const MAX_FORECAST_OUTPUT_POINTS = 250

const MINUTES_PER_DAY = 60 * 24
const SUPPORTED_FORECAST_INTERVALS: ReadonlySet<IntervalType> = new Set(['hour', 'day', 'week', 'month'])

export function intervalSupportsForecast(interval: IntervalType | null | undefined): boolean {
    return interval == null || SUPPORTED_FORECAST_INTERVALS.has(interval)
}

/** Both displays keep the insight's interval, so they read as a time series, but neither returns
 * one to fit: the box plot returns a distribution per bucket, and the slope keeps only the first
 * and last bucket. */
const UNFORECASTABLE_DISPLAYS: ReadonlySet<ChartDisplayType> = new Set([
    ChartDisplayType.BoxPlot,
    ChartDisplayType.SlopeGraph,
])

export function displaySupportsForecast(display: ChartDisplayType | null | undefined): boolean {
    return display == null || !UNFORECASTABLE_DISPLAYS.has(display)
}

export function maxHorizonForInterval(interval: IntervalType | null | undefined): number {
    const minutes = INSIGHT_INTERVAL_DURATION_MINUTES[interval ?? 'day']
    return Math.min(MAX_FORECAST_OUTPUT_POINTS, Math.ceil((MAX_FORECAST_REACH_DAYS * MINUTES_PER_DAY) / minutes))
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
    const days = dayjs(targetDate).startOf('day').diff(today.startOf('day'), 'day')
    if (days <= 0) {
        return 'The target date must be in the future.'
    }
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
