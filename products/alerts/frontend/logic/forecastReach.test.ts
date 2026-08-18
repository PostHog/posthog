import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import { forecastTargetDateError, maxHorizonForInterval } from './forecastReach'

describe('maxHorizonForInterval', () => {
    // A forecast may reach at most MAX_FORECAST_REACH_DAYS ahead, so the horizon ceiling depends on
    // the interval. A fixed ceiling refuses most of the valid hourly range and overshoots monthly.
    it.each([
        [AlertCalculationInterval.HOURLY, 4392],
        [AlertCalculationInterval.DAILY, 183],
        [AlertCalculationInterval.WEEKLY, 26],
        [AlertCalculationInterval.MONTHLY, 6],
    ])('caps %s at %i intervals', (interval, expected) => {
        expect(maxHorizonForInterval(interval)).toBe(expected)
    })
})

describe('forecastTargetDateError', () => {
    const today = new Date('2026-08-18')

    // The backend rejects these at simulate and at save. Catching them here means the user is told
    // while typing rather than after a round trip that fails.
    it.each([
        ['inside the cap', '2026-11-16', null],
        ['beyond the cap', '2027-05-12', 'within 6 months'],
        ['in the past', '2026-01-01', 'in the future'],
        ['today is not the future', '2026-08-18', 'in the future'],
    ])('%s', (_name, targetDate, expected) => {
        const error = forecastTargetDateError(targetDate, today)
        expected === null ? expect(error).toBeNull() : expect(error).toContain(expected)
    })

    it('is null when no date is set yet', () => {
        expect(forecastTargetDateError(undefined, today)).toBeNull()
    })
})
