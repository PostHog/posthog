import { dayjs } from 'lib/dayjs'

import { forecastTargetDateError, maxHorizonForInterval } from './forecastReach'

describe('maxHorizonForInterval', () => {
    // Keyed by the INSIGHT's interval, not the check cadence. The backend counts horizon in insight
    // buckets, so a weekly insight checked daily must still cap in weeks or the editor offers
    // horizons the save path rejects.
    it.each([
        ['hour' as const, 4392],
        ['day' as const, 183],
        ['week' as const, 26],
        ['month' as const, 6],
    ])('caps a %s insight at %i intervals', (interval, expected) => {
        expect(maxHorizonForInterval(interval)).toBe(expected)
    })

    it('treats a missing interval as daily', () => {
        expect(maxHorizonForInterval(null)).toBe(183)
    })
})

describe('forecastTargetDateError', () => {
    const today = dayjs('2026-08-18')

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
