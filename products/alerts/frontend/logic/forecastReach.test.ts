import { dayjs } from 'lib/dayjs'

import { ChartDisplayType, IntervalType } from '~/types'

import {
    clampHorizon,
    displaySupportsForecast,
    forecastTargetDateError,
    intervalSupportsForecast,
    maxHorizonForInterval,
    minForecastPoints,
    pointsInSimulationRange,
    usableSimulationRanges,
} from './forecastReach'

describe('maxHorizonForInterval', () => {
    it.each([
        ['hour' as const, 250],
        ['day' as const, 92],
        ['week' as const, 14],
        ['month' as const, 4],
    ])('caps a %s insight at %i intervals', (interval, expected) => {
        expect(maxHorizonForInterval(interval)).toBe(expected)
    })

    it('treats a missing interval as daily', () => {
        expect(maxHorizonForInterval(null)).toBe(92)
    })
})

describe('forecastTargetDateError', () => {
    const today = dayjs('2026-09-07')

    it.each([
        ['inside the cap', '2026-12-08', 'day', null],
        ['beyond the cap', '2026-12-09', 'day', 'within 92 days'],
        ['in the past', '2026-01-01', 'day', 'in the future'],
        ['today is not the future', '2026-09-07', 'day', 'in the future'],
        ['hourly fits within 250 points', '2026-09-17', 'hour', null],
        ['hourly would exceed 250 points', '2026-09-18', 'hour', 'coarser insight interval'],
    ] as const)('%s', (_name, targetDate, interval, expected) => {
        const error = forecastTargetDateError(targetDate, today, interval)
        expected === null ? expect(error).toBeNull() : expect(error).toContain(expected)
    })

    it('asks for a date when none is set', () => {
        expect(forecastTargetDateError(undefined, today)).toBe('Choose a target date')
    })
})

describe('clampHorizon', () => {
    it.each([
        ['pulls a horizon down to the cap', 100, 'week', 14],
        ['leaves a horizon inside the cap', 7, 'day', 7],
        ['raises a horizon below one', 0, 'day', 1],
        ['rounds a fractional horizon up to a whole interval', 1.5, 'day', 2],
        ['rounds a fractional horizon down to a whole interval', 7.4, 'day', 7],
    ] as const)('%s', (_name, horizon, interval, expected) => {
        expect(clampHorizon({ horizon }, interval).horizon).toBe(expected)
    })

    it('returns the same object when nothing changes', () => {
        const config = { horizon: 7 }
        expect(clampHorizon(config, 'day')).toBe(config)
    })
})

describe('forecast prerequisites', () => {
    it.each([
        ['hour', true],
        ['day', true],
        ['week', true],
        ['month', true],
        ['minute', false],
    ] as const)('supports %s: %s', (interval, expected) => {
        expect(intervalSupportsForecast(interval)).toBe(expected)
    })

    it('requires extra hourly history', () => {
        expect(minForecastPoints('hour')).toBe(48)
        expect(minForecastPoints('day')).toBe(14)
    })
})

describe('displaySupportsForecast', () => {
    it.each([
        ['a line graph', ChartDisplayType.ActionsLineGraph, true],
        ['an area graph', ChartDisplayType.ActionsAreaGraph, true],
        ['a bar chart', ChartDisplayType.ActionsBar, true],
        // Both keep the insight's interval, so the time-series check alone lets them through.
        ['a box plot', ChartDisplayType.BoxPlot, false],
        ['a slope graph', ChartDisplayType.SlopeGraph, false],
    ])('%s', (_name, display, expected) => {
        expect(displaySupportsForecast(display)).toBe(expected)
    })

    it('allows an insight with no display set', () => {
        expect(displaySupportsForecast(null)).toBe(true)
    })
})

describe('pointsInSimulationRange', () => {
    // PostHog reads lowercase `m` as months and uppercase `M` as minutes.
    it.each([
        ['months on a daily insight', '-12m', 'day', 360],
        ['months on a monthly insight', '-24m', 'month', 24],
        ['minutes on an hourly insight', '-90M', 'hour', 1],
        ['days on a daily insight', '-90d', 'day', 90],
        ['weeks on a weekly insight', '-12w', 'week', 12],
        ['hours on an hourly insight', '-48h', 'hour', 48],
    ] as const)('%s', (_name, range, interval, expected) => {
        expect(pointsInSimulationRange(range, interval as IntervalType)).toBe(expected)
    })
})

describe('usableSimulationRanges', () => {
    const monthlyOptions = [{ value: '-6m' }, { value: '-12m' }, { value: '-24m' }]

    it('keeps every monthly range for a daily insight', () => {
        expect(usableSimulationRanges(monthlyOptions, 'day')).toEqual(monthlyOptions)
    })

    it('drops the monthly ranges that are too short for a monthly insight', () => {
        expect(usableSimulationRanges(monthlyOptions, 'month')).toEqual([{ value: '-24m' }])
    })
})
