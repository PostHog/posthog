import { dayjs } from 'lib/dayjs'

import { ForecastConditionType, ForecastEngineType, ForecastTargetDirection } from '~/queries/schema/schema-general'

import { forecastTargetDateError } from '../logic/forecastReach'
import { getDefaultForecastConfig, withConditionDefaults } from './ForecastSelector'

describe('withConditionDefaults', () => {
    const base = {
        type: 'ForecastConfig' as const,
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: 100,
        interval_width: 0.8,
    }

    // Each condition reads a different subset, and unread fields still reach the engine: a stale
    // horizon inflates the query window, and a stale band width moves when a breach fires with no
    // control on screen showing it.
    it('drops the horizon when leaving predicted-to-breach', () => {
        expect(withConditionDefaults(base, ForecastConditionType.BAND_DEVIATION).horizon).toBeUndefined()
        expect(withConditionDefaults(base, ForecastConditionType.TARGET_BY_DATE).horizon).toBeUndefined()
    })

    it('keeps the horizon on predicted-to-breach', () => {
        expect(withConditionDefaults(base, ForecastConditionType.FUTURE_BREACH).horizon).toBe(100)
    })

    it('resets the band width outside expected-range', () => {
        expect(withConditionDefaults(base, ForecastConditionType.FUTURE_BREACH).interval_width).toBe(0.95)
        expect(withConditionDefaults(base, ForecastConditionType.BAND_DEVIATION).interval_width).toBe(0.8)
    })

    it('seeds a target with a direction and an in-range date', () => {
        const next = withConditionDefaults(base, ForecastConditionType.TARGET_BY_DATE)
        expect(next.target_direction).toBe(ForecastTargetDirection.AT_LEAST)
        expect(forecastTargetDateError(next.target_date, dayjs())).toBeNull()
    })
})

describe('getDefaultForecastConfig', () => {
    // The seed is a second write path alongside load. Seeding 7 on a monthly insight, where the cap
    // is 6, sent a horizon the user never typed and the save rejected.
    it.each([
        ['clamps the seeded horizon to a monthly cap', 'month', 6],
        ['leaves the seeded horizon alone where it fits', 'day', 7],
    ] as const)('%s', (_n, interval, expected) => {
        expect(getDefaultForecastConfig(interval).horizon).toBe(expected)
    })
})
