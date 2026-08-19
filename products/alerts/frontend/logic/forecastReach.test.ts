import { dayjs } from 'lib/dayjs'

import { clampHorizon, forecastTargetDateError, intervalSupportsForecast, maxHorizonForInterval } from './forecastReach'

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

describe('clampHorizon', () => {
    // The editor used to clamp for display only, so an insight whose interval changed after the
    // alert was saved showed one number and submitted another, and the save 400d on a value the
    // user never saw.
    it.each([
        ['pulls a horizon down to the cap', 100, 'week', 26],
        ['leaves a horizon inside the cap', 7, 'day', 7],
        ['raises a horizon below one', 0, 'day', 1],
    ] as const)('%s', (_n, horizon, interval, expected) => {
        expect(clampHorizon({ horizon }, interval).horizon).toBe(expected)
    })

    it('returns the same object when nothing changes, so React sees no new config', () => {
        const config = { horizon: 7 }
        expect(clampHorizon(config, 'day')).toBe(config)
    })

    it('leaves a config with no horizon alone', () => {
        expect(clampHorizon({ target: 5 } as { horizon?: number; target: number }, 'month')).toEqual({ target: 5 })
    })
})

describe('intervalSupportsForecast', () => {
    // Mirrors SUPPORTED_FORECAST_INTERVALS on the backend. Offering the mode where the save path
    // rejects it is what this guard exists to stop.
    it.each([
        ['hour', true],
        ['day', true],
        ['week', true],
        ['month', true],
        ['minute', false],
    ] as const)('%s', (interval, expected) => {
        expect(intervalSupportsForecast(interval)).toBe(expected)
    })

    it('treats a missing interval as the daily default', () => {
        expect(intervalSupportsForecast(null)).toBe(true)
    })
})

describe('forecastTargetDateError anchors on the last completed bucket', () => {
    const today = dayjs('2026-06-01')

    // Mirrors save_time_anchor on the backend. Measuring from today instead would accept a date the
    // first scheduled check then rejects, which auto-disables the alert and emails its subscribers.
    it.each([
        ['daily keeps the full reach', 'day', 183, null],
        [
            'daily rejects one day past it',
            'day',
            184,
            'A forecast target must be within 6 months. Move the date closer.',
        ],
        ['weekly loses the six days the bucket occupies', 'week', 177, null],
        [
            'weekly rejects one day past that',
            'week',
            179,
            'A forecast target must be within 6 months. Move the date closer.',
        ],
        ['monthly loses a month', 'month', 153, null],
        [
            'monthly rejects one day past that',
            'month',
            154,
            'A forecast target must be within 6 months. Move the date closer.',
        ],
    ] as const)('%s', (_n, interval, daysAhead, expected) => {
        const target = today.add(daysAhead, 'day').format('YYYY-MM-DD')
        expect(forecastTargetDateError(target, today, interval)).toBe(expected)
    })
})
