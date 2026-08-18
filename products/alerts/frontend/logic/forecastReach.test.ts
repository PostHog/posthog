import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import { maxHorizonForInterval } from './forecastReach'

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
