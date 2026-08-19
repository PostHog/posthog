import { dayjs } from 'lib/dayjs'

import { ForecastErrorMode } from '~/queries/schema/schema-general'

import {
    clampHorizon,
    forecastErrorThresholdError,
    forecastTargetDateError,
    intervalSupportsForecast,
    maxHorizonForInterval,
} from './forecastReach'

describe('maxHorizonForInterval', () => {
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

describe('forecastTargetDateError measures reach from today', () => {
    const today = dayjs('2026-06-01')

    it.each(['hour', 'day', 'week', 'month'] as const)('%s allows the full six months', (interval) => {
        void interval
        expect(forecastTargetDateError(today.add(183, 'day').format('YYYY-MM-DD'), today)).toBeNull()
        expect(forecastTargetDateError(today.add(184, 'day').format('YYYY-MM-DD'), today)).toBe(
            'A forecast target must be within 6 months. Move the date closer.'
        )
    })
})

describe('forecastErrorThresholdError', () => {
    it.each([
        ['percentage mode with no value', { error_mode: ForecastErrorMode.RELATIVE }, 'Enter a percentage above zero'],
        [
            'percentage mode at zero',
            { error_mode: ForecastErrorMode.RELATIVE, error_threshold_pct: 0 },
            'Enter a percentage above zero',
        ],
        ['percentage mode with a value', { error_mode: ForecastErrorMode.RELATIVE, error_threshold_pct: 0.2 }, null],
        ['fixed mode with no value', { error_mode: ForecastErrorMode.ABSOLUTE }, 'Enter an amount above zero'],
        ['fixed mode with a value', { error_mode: ForecastErrorMode.ABSOLUTE, error_threshold_abs: 50 }, null],
        ['expected-range mode needs neither', { error_mode: ForecastErrorMode.PREDICTION_INTERVAL }, null],
        ['an unset mode needs neither', {}, null],
    ] as const)('%s', (_n, config, expected) => {
        expect(forecastErrorThresholdError(config)).toBe(expected)
    })
})
