import { dayjs } from 'lib/dayjs'

import {
    ForecastConditionType,
    ForecastConfig,
    ForecastEngineType,
    ForecastTargetDirection,
} from '~/queries/schema/schema-general'

import { forecastTargetDateError, forecastTargetValueError } from '../logic/forecastReach'
import { getDefaultForecastConfig, withConditionDefaults } from './ForecastSelector'

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
