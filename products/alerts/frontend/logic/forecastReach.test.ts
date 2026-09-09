import { dayjs } from 'lib/dayjs'

import { AlertCalculationInterval, DateRange } from '~/queries/schema/schema-general'
import { ChartDisplayType, IntervalType } from '~/types'

import {
    clampHorizon,
    dateRangeSupportsForecast,
    defaultHorizonForInterval,
    displaySupportsForecast,
    forecastTargetDateError,
    forecastTargetIntervalError,
    intervalSupportsForecast,
    maxHorizonForInterval,
    minForecastPoints,
    targetByDateSupportsForecast,
    pointsInSimulationRange,
    resolveForecastSimulationRange,
    resolveHorizon,
    smoothingSupportsForecast,
    usableSimulationRanges,
} from './forecastReach'

describe('maxHorizonForInterval', () => {
    // The backend refuses a horizon reaching past 92 days, counting a month as 30.4 days, so
    // 13 weeks (91) and 3 months (91.2) are the last values it accepts.
    it.each([
        ['hour' as const, 250],
        ['day' as const, 92],
        ['week' as const, 13],
        ['month' as const, 3],
    ])('caps a %s insight at %i intervals', (interval, expected) => {
        expect(maxHorizonForInterval(interval)).toBe(expected)
    })

    const BACKEND_INTERVAL_DAYS = { hour: 1 / 24, day: 1, week: 7, month: 30.4 } as const

    it.each(['hour', 'day', 'week', 'month'] as const)('stays inside the backend reach for %s', (interval) => {
        expect(maxHorizonForInterval(interval) * BACKEND_INTERVAL_DAYS[interval]).toBeLessThanOrEqual(92)
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
        ['pulls a horizon down to the cap', 100, 'week', 13],
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

describe('resolveHorizon', () => {
    // A config saved through the API can leave the horizon out; the backend then resolves
    // default_horizon(interval), so the editor has to show that same number.
    it.each<[string, { horizon?: number | null }, IntervalType | null, number]>([
        ['a missing monthly horizon', {}, 'month', 3],
        ['a null monthly horizon', { horizon: null }, 'month', 3],
        ['a missing daily horizon', {}, 'day', 7],
        ['a missing weekly horizon', {}, 'week', 7],
        ['a missing horizon with no interval set', {}, null, 7],
        ['a stored horizon inside the cap', { horizon: 2 }, 'month', 2],
        ['a stored horizon above the cap', { horizon: 7 }, 'month', 3],
    ])('%s resolves to %i', (_name, config, interval, expected) => {
        expect(resolveHorizon(config, interval).horizon).toBe(expected)
    })

    it('matches the default the backend would resolve', () => {
        expect(defaultHorizonForInterval('month')).toBe(3)
        expect(defaultHorizonForInterval('day')).toBe(7)
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
        ['a cumulative line graph', ChartDisplayType.ActionsLineGraphCumulative, false],
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

describe('dateRangeSupportsForecast', () => {
    // Mirrors validate_forecast_days_of_week: only a day interval charts a gapped history.
    it.each<[string, DateRange | undefined, IntervalType | null, boolean]>([
        ['no date range', undefined, 'day', true],
        ['no day selection', { date_from: '-30d' }, 'day', true],
        ['a null day selection', { daysOfWeek: null }, 'day', true],
        ['an empty day selection', { daysOfWeek: [] }, 'day', true],
        ['all seven days', { daysOfWeek: [1, 2, 3, 4, 5, 6, 7] }, 'day', true],
        ['weekdays only', { daysOfWeek: [1, 2, 3, 4, 5] }, 'day', false],
        ['weekdays only with no interval set', { daysOfWeek: [1, 2, 3, 4, 5] }, null, false],
        ['weekdays only on a weekly insight', { daysOfWeek: [1, 2, 3, 4, 5] }, 'week', true],
        ['weekdays only on a monthly insight', { daysOfWeek: [1, 2, 3, 4, 5] }, 'month', true],
    ])('%s', (_name, dateRange, interval, expected) => {
        expect(dateRangeSupportsForecast(dateRange, interval)).toBe(expected)
    })
})

describe('smoothingSupportsForecast', () => {
    it.each([
        [undefined, true],
        [null, true],
        [1, true],
        [2, false],
        [14, false],
    ])('supports %s smoothing intervals: %s', (smoothingIntervals, expected) => {
        expect(smoothingSupportsForecast(smoothingIntervals)).toBe(expected)
    })
})

describe('targetByDateSupportsForecast', () => {
    it.each([
        ['hour', false],
        ['day', true],
        ['week', true],
        ['month', true],
    ] as const)('supports %s: %s', (interval, expected) => {
        expect(targetByDateSupportsForecast(interval)).toBe(expected)
    })

    // The save and simulate paths both refuse an hourly target, so the editor has to say why.
    it.each([
        ['hour', 'Target-by-date forecasts need a daily, weekly, or monthly insight interval.'],
        ['day', null],
        ['week', null],
        ['month', null],
        [null, null],
    ] as const)('reports %s as %s', (interval, expected) => {
        expect(forecastTargetIntervalError(interval)).toBe(expected)
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

describe('resolveForecastSimulationRange', () => {
    it('keeps a stored range that the cadence still offers', () => {
        expect(resolveForecastSimulationRange('-60d', AlertCalculationInterval.DAILY, 'day')).toBe('-60d')
    })

    it('uses the cadence default when nothing is stored', () => {
        expect(resolveForecastSimulationRange(null, AlertCalculationInterval.DAILY, 'day')).toBe('-30d')
    })

    // Picking "Last 90d" on a daily cadence and then switching the cadence to weekly leaves a range
    // the weekly select cannot show, so the request has to move with the control.
    it('replaces a stored range the new cadence does not offer', () => {
        expect(resolveForecastSimulationRange('-90d', AlertCalculationInterval.WEEKLY, 'day')).toBe('-8w')
    })

    // The monthly default is 12 months, which is under the 14 completed intervals a monthly insight
    // needs, so the only usable option is the one the control falls back to.
    it('replaces a default that is too short for the insight interval', () => {
        expect(resolveForecastSimulationRange(null, AlertCalculationInterval.MONTHLY, 'month')).toBe('-24m')
    })
})
