import { AlertCalculationInterval } from '~/queries/schema/schema-general'

/** Kept in step with MAX_FORECAST_REACH_DAYS in products/alerts/backend/forecasting/engine.py,
 *  which is the source of truth. Same name in both languages so one grep finds both halves. */
export const MAX_FORECAST_REACH_DAYS = 183

const MS_PER_DAY = 24 * 60 * 60 * 1000

/** Days each interval covers. Mirrors _INTERVAL_DAYS in the same backend module. */
const INTERVAL_DAYS: Record<AlertCalculationInterval, number> = {
    [AlertCalculationInterval.REAL_TIME]: 1 / 24,
    [AlertCalculationInterval.EVERY_15_MINUTES]: 1 / 96,
    [AlertCalculationInterval.HOURLY]: 1 / 24,
    [AlertCalculationInterval.DAILY]: 1,
    [AlertCalculationInterval.WEEKLY]: 7,
    [AlertCalculationInterval.MONTHLY]: 30.4,
}

/** How many intervals a forecast may look ahead. The backend caps reach as a duration, so a fixed
 *  ceiling would refuse most of the valid hourly range and accept far too much on monthly. */
export function maxHorizonForInterval(interval: AlertCalculationInterval): number {
    return Math.floor(MAX_FORECAST_REACH_DAYS / (INTERVAL_DAYS[interval] ?? 1))
}

/** Why a target date cannot be forecast, or null when it can. Mirrors horizon_for_target_date in
 *  products/alerts/backend/forecasting/engine.py so the editor and the server agree on the wording. */
export function forecastTargetDateError(targetDate: string | undefined, today: Date): string | null {
    if (!targetDate) {
        return null
    }
    const days = Math.floor((new Date(targetDate).getTime() - today.getTime()) / MS_PER_DAY)
    if (days <= 0) {
        return 'The target date must be in the future.'
    }
    if (days > MAX_FORECAST_REACH_DAYS) {
        return 'A forecast target must be within 6 months. Move the date closer, or use an insight with a coarser interval.'
    }
    return null
}
