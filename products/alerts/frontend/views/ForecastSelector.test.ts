import { dayjs } from 'lib/dayjs'

import {
    ForecastConditionType,
    ForecastEngineType,
    ForecastErrorMode,
    ForecastTargetDirection,
} from '~/queries/schema/schema-general'

import { forecastTargetDateError } from '../logic/forecastReach'
import { getDefaultForecastConfig, withConditionDefaults, withErrorModeDefaults } from './ForecastSelector'

describe('withConditionDefaults', () => {
    const base = {
        type: 'ForecastConfig' as const,
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: 100,
        interval_width: 0.8,
    }

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
    it.each([
        ['clamps the seeded horizon to a monthly cap', 'month', 6],
        ['leaves the seeded horizon alone where it fits', 'day', 7],
    ] as const)('%s', (_n, interval, expected) => {
        expect(getDefaultForecastConfig(interval).horizon).toBe(expected)
    })
})

describe('withErrorModeDefaults', () => {
    const band = {
        type: 'ForecastConfig' as const,
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.BAND_DEVIATION,
        error_threshold_pct: 0.2,
        error_threshold_abs: 50,
        score_threshold: 0.75,
    }

    it.each([
        ['percentage keeps only its own threshold', ForecastErrorMode.RELATIVE, ['error_threshold_pct']],
        ['fixed amount keeps only its own threshold', ForecastErrorMode.ABSOLUTE, ['error_threshold_abs']],
        ['expected range keeps only the score cutoff', ForecastErrorMode.PREDICTION_INTERVAL, ['score_threshold']],
    ] as const)('%s', (_n, mode, kept) => {
        const next = withErrorModeDefaults(band, mode)
        for (const field of ['error_threshold_pct', 'error_threshold_abs', 'score_threshold'] as const) {
            expect(next[field] === undefined).toBe(!kept.includes(field as never))
        }
        expect(next.error_mode).toBe(mode)
    })

    it('seeds a percentage so the mode does not start in an invalid state', () => {
        expect(
            withErrorModeDefaults({ ...band, error_threshold_pct: undefined }, ForecastErrorMode.RELATIVE)
                .error_threshold_pct
        ).toBe(0.2)
    })
})

describe('withConditionDefaults clears band-only fields', () => {
    it.each([ForecastConditionType.FUTURE_BREACH, ForecastConditionType.TARGET_BY_DATE] as const)(
        'leaving band deviation for %s',
        (condition) => {
            const next = withConditionDefaults(
                {
                    type: 'ForecastConfig',
                    engine: ForecastEngineType.PROPHET,
                    condition: ForecastConditionType.BAND_DEVIATION,
                    direction: 'below' as never,
                    error_mode: ForecastErrorMode.RELATIVE,
                    error_threshold_pct: 0.2,
                    error_threshold_abs: 50,
                    score_threshold: 0.75,
                },
                condition
            )
            expect(next.direction).toBeUndefined()
            expect(next.error_mode).toBeUndefined()
            expect(next.error_threshold_pct).toBeUndefined()
            expect(next.error_threshold_abs).toBeUndefined()
            expect(next.score_threshold).toBeUndefined()
        }
    )
})
