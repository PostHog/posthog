import { AlertCalculationInterval } from '~/queries/schema/schema-general'

/** Kept in step with MAX_FORECAST_REACH_DAYS in products/alerts/backend/forecasting/engine.py,
 *  which is the source of truth. Same name in both languages so one grep finds both halves. */
export const MAX_FORECAST_REACH_DAYS = 183

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
