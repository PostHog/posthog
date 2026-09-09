import { cleanup, render } from '@testing-library/react'

import { dayjs } from 'lib/dayjs'

import {
    ForecastConditionType,
    ForecastConfig,
    ForecastEngineType,
    ForecastTargetDirection,
    FutureBreachForecastConfig,
} from '~/queries/schema/schema-general'

import { forecastTargetDateError, forecastTargetValueError } from '../logic/forecastReach'
import {
    ForecastSelector,
    getDefaultForecastConfig,
    withConditionDefaults,
    withEnteredHorizon,
} from './ForecastSelector'

describe('withConditionDefaults', () => {
    const futureBreach: ForecastConfig = {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: 12,
    }

    it('switches to a target with a date inside the quarterly cap and an empty target', () => {
        const today = dayjs('2026-09-07')
        const next = withConditionDefaults(futureBreach, ForecastConditionType.TARGET_BY_DATE, today)

        expect(next.condition).toBe(ForecastConditionType.TARGET_BY_DATE)
        if (next.condition !== ForecastConditionType.TARGET_BY_DATE) {
            throw new Error('Expected target-by-date config')
        }
        expect(next.target_direction).toBe(ForecastTargetDirection.AT_LEAST)
        expect(forecastTargetValueError(next.target)).toBe('Enter a target value')
        expect(forecastTargetDateError(next.target_date, today, 'day')).toBeNull()
        expect(next).not.toHaveProperty('horizon')
    })

    it.each(['hour', 'day', 'week', 'month'] as const)(
        'seeds a target date the %s insight can reach, so the path does not open in an error state',
        (interval) => {
            const today = dayjs('2026-09-07')
            const next = withConditionDefaults(futureBreach, ForecastConditionType.TARGET_BY_DATE, today, interval)

            if (next.condition !== ForecastConditionType.TARGET_BY_DATE) {
                throw new Error('Expected target-by-date config')
            }
            expect(forecastTargetDateError(next.target_date, today, interval)).toBeNull()
        }
    )

    it('switches back to a breach without carrying target fields', () => {
        const next = withConditionDefaults(
            {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target: 100,
                target_direction: ForecastTargetDirection.AT_LEAST,
                target_date: '2026-10-01',
            },
            ForecastConditionType.FUTURE_BREACH
        )

        expect(next).toEqual({
            type: 'ForecastConfig',
            engine: ForecastEngineType.PROPHET,
            condition: ForecastConditionType.FUTURE_BREACH,
            horizon: 7,
        })
    })

    it('keeps the restored horizon inside the cap of a coarse insight', () => {
        const next = withConditionDefaults(
            {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target: 100,
                target_direction: ForecastTargetDirection.AT_LEAST,
                target_date: '2026-10-01',
            },
            ForecastConditionType.FUTURE_BREACH,
            dayjs('2026-09-07'),
            'month'
        )

        expect(next).toHaveProperty('horizon', 3)
    })
})

describe('withEnteredHorizon', () => {
    const breachConfig = (horizon: number | undefined): FutureBreachForecastConfig => ({
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon,
    })

    it.each([
        // Clearing the field reports NaN. Storing it would save a null horizon that silently
        // evaluates as the backend default, dropping a longer look-ahead the user had set.
        ['keeps the set horizon when the field is cleared', 30, Number.NaN, 'day', 30],
        ['takes a number the user typed', 30, 14, 'day', 14],
        ['clamps a typed horizon to the interval cap', 7, 100, 'week', 13],
        ['falls back to the default when no horizon is set yet', undefined, Number.NaN, 'day', 7],
    ] as const)('%s', (_name, current, entered, interval, expected) => {
        const next = withEnteredHorizon(breachConfig(current), entered, interval)

        if (next.condition !== ForecastConditionType.FUTURE_BREACH) {
            throw new Error('Expected future-breach config')
        }
        expect(next.horizon).toBe(expected)
    })
})

describe('getDefaultForecastConfig', () => {
    it.each([
        ['clamps the seeded horizon to a monthly cap', 'month', 3],
        ['leaves the seeded horizon alone where it fits', 'day', 7],
    ] as const)('%s', (_name, interval, expected) => {
        const config = getDefaultForecastConfig(interval)
        expect(config.condition).toBe(ForecastConditionType.FUTURE_BREACH)
        if (config.condition === ForecastConditionType.FUTURE_BREACH) {
            expect(config.horizon).toBe(expected)
        }
    })
})

// The form permits an expired target date the user has not changed, so an alert whose date has
// passed can still be renamed or turned off. The selector must show the form's verdict on the date
// instead of its own, or that supported edit reads as invalid.
describe('ForecastSelector', () => {
    beforeEach(cleanup)

    const expiredTarget = {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.TARGET_BY_DATE,
        target: 100,
        target_direction: ForecastTargetDirection.AT_LEAST,
        target_date: dayjs().subtract(1, 'year').format('YYYY-MM-DD'),
    } as const satisfies ForecastConfig

    const targetOn = (target_date: string): ForecastConfig => ({ ...expiredTarget, target_date })

    // The server accepts every ISO date form and stores what it was sent, so a stored date can be
    // one dayjs cannot read. The date button has to show it rather than the words "Invalid Date".
    it.each([
        ['a week date dayjs cannot read', '2026-W40-1', '2026-W40-1'],
        ['an ordinary date', '2026-12-01', 'December 1, 2026'],
    ] as const)('shows %s on the date button', (_name, targetDate, expected) => {
        const { container } = render(
            <ForecastSelector
                value={targetOn(targetDate)}
                onChange={() => {}}
                insightInterval="day"
                targetDateError={null}
            />
        )

        expect(container.querySelector('[data-attr="alertForm-forecast-target-date"]')?.textContent).toBe(expected)
    })

    it.each([
        ['shows nothing when the form accepts the date', null, null],
        ['shows the form message when the form rejects it', 'Choose a target date', 'Choose a target date'],
    ] as const)('%s', (_name, targetDateError, expected) => {
        const { container } = render(
            <ForecastSelector
                value={expiredTarget}
                onChange={() => {}}
                insightInterval="day"
                targetDateError={targetDateError}
            />
        )

        const error = container.querySelector('[data-attr="alertForm-forecast-target-error"]')
        expect(error?.textContent ?? null).toBe(expected)
    })
})
