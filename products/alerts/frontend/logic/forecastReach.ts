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
