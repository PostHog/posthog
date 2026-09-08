import { dayjs } from 'lib/dayjs'

import {
    AlertCalculationInterval,
    AlertConditionType,
    ForecastConditionType,
    ForecastTargetDirection,
    ForecastEngineType,
    InsightThresholdType,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { AlertFormType } from './alertFormLogic'
import { getAlertFormValidationErrors, THRESHOLD_BOUNDS_FORM_ERROR, thresholdAlertHasBounds } from './alertFormSchema'

const baseAlert: AlertFormType = {
    name: 'My alert',
    enabled: true,
    created_by: null,
    created_at: '',
    config: {
        type: 'TrendsAlertConfig',
        series_index: 0,
        check_ongoing_interval: false,
    },
    threshold: {
        configuration: {
            type: InsightThresholdType.ABSOLUTE,
            bounds: { upper: 100 },
        },
    },
    condition: { type: AlertConditionType.ABSOLUTE_VALUE },
    subscribed_users: [],
    checks: [],
    calculation_interval: AlertCalculationInterval.DAILY,
    skip_weekend: false,
    schedule_restriction: null,
    detector_config: null,
    insight: 42,
}

describe('alertFormSchema', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('returns no errors for a valid threshold alert', () => {
        expect(getAlertFormValidationErrors(baseAlert)).toEqual({})
    })

    it('requires a name', () => {
        expect(getAlertFormValidationErrors({ ...baseAlert, name: '' }).name).toBe('You need to give your alert a name')
    })

    it('requires at least one threshold bound for non-detector alerts', () => {
        const errors = getAlertFormValidationErrors({
            ...baseAlert,
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: {},
                },
            },
        })
        expect(errors.threshold).toBe(THRESHOLD_BOUNDS_FORM_ERROR)
        expect(
            thresholdAlertHasBounds({
                ...baseAlert,
                threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: {} } },
            })
        ).toBe(false)
    })

    it('requires the lower threshold to be below the upper threshold', () => {
        const errors = getAlertFormValidationErrors({
            ...baseAlert,
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { lower: 5, upper: 1 },
                },
            },
        })

        expect(errors.threshold).toBe('The “Less than” value must be lower than the “More than” value')
    })

    it('rejects negative thresholds for relative conditions', () => {
        const errors = getAlertFormValidationErrors({
            ...baseAlert,
            condition: { type: AlertConditionType.RELATIVE_DECREASE },
            threshold: {
                configuration: {
                    type: InsightThresholdType.ABSOLUTE,
                    bounds: { upper: -1 },
                },
            },
        })

        expect(errors.threshold).toBe('Enter zero or a positive change value')
    })

    it('treats cleared threshold inputs as missing bounds', () => {
        expect(
            thresholdAlertHasBounds({
                ...baseAlert,
                threshold: {
                    configuration: {
                        type: InsightThresholdType.ABSOLUTE,
                        bounds: { lower: '' as unknown as number, upper: '' as unknown as number },
                    },
                },
            })
        ).toBe(false)
    })

    it.each([{}, null])('skips threshold bounds when detector_config is set and bounds are %p', (bounds) => {
        expect(
            getAlertFormValidationErrors({
                ...baseAlert,
                detector_config: { type: 'zscore', threshold: 3 },
                threshold: {
                    configuration: {
                        type: InsightThresholdType.ABSOLUTE,
                        bounds,
                    },
                },
            })
        ).toEqual({})
    })

    it('does not require threshold bounds for a target-by-date forecast', () => {
        expect(
            thresholdAlertHasBounds({
                ...baseAlert,
                forecast_config: {
                    type: 'ForecastConfig',
                    engine: ForecastEngineType.PROPHET,
                    condition: ForecastConditionType.TARGET_BY_DATE,
                    target: 100,
                    target_direction: ForecastTargetDirection.AT_LEAST,
                    target_date: '2026-12-31',
                },
                threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: {} } },
            })
        ).toBe(true)
    })

    it('ignores stale hidden threshold bounds for a target-by-date forecast', () => {
        const errors = getAlertFormValidationErrors({
            ...baseAlert,
            forecast_config: {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target: 100,
                target_direction: ForecastTargetDirection.AT_LEAST,
                target_date: dayjs().add(30, 'day').format('YYYY-MM-DD'),
            },
            threshold: {
                configuration: { type: InsightThresholdType.ABSOLUTE, bounds: { lower: 10, upper: 5 } },
            },
        })

        expect(errors).toEqual({})
    })

    it.each([
        [
            'a forecast cadence finer than the insight interval',
            AlertCalculationInterval.DAILY,
            true,
            "A forecast alert cannot run more often than the insight's week interval. Choose a slower cadence.",
        ],
        ['a forecast cadence matching the insight interval', AlertCalculationInterval.WEEKLY, true, undefined],
        ['a threshold cadence finer than the insight interval', AlertCalculationInterval.DAILY, false, undefined],
    ] as const)('%s', (_name, calculation_interval, isForecast, expected) => {
        const errors = getAlertFormValidationErrors(
            {
                ...baseAlert,
                calculation_interval,
                forecast_config: isForecast
                    ? {
                          type: 'ForecastConfig',
                          engine: ForecastEngineType.PROPHET,
                          condition: ForecastConditionType.FUTURE_BREACH,
                      }
                    : null,
            },
            { insightInterval: 'week' }
        )

        expect(errors.calculation_interval).toBe(expected)
    })

    it('requires threshold bounds for a future-breach forecast', () => {
        expect(
            thresholdAlertHasBounds({
                ...baseAlert,
                forecast_config: {
                    type: 'ForecastConfig',
                    engine: ForecastEngineType.PROPHET,
                    condition: ForecastConditionType.FUTURE_BREACH,
                },
                threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: {} } },
            })
        ).toBe(false)
    })
})

describe('a target alert whose date has passed', () => {
    const savedForecastConfig = {
        type: 'ForecastConfig' as const,
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.TARGET_BY_DATE,
        target: 100,
        target_direction: ForecastTargetDirection.AT_LEAST,
        target_date: '2020-01-01',
    }
    const finishedAlert: AlertFormType = { ...baseAlert, forecast_config: savedForecastConfig }

    const savedTargetDate = savedForecastConfig.target_date

    it.each([
        ['nothing about the forecast changed', {}],
        ['only the target changed', { target: 250 }],
        ['only the direction changed', { target_direction: ForecastTargetDirection.AT_MOST }],
    ] as const)('saves when %s, so it can still be renamed or turned off', (_n, patch) => {
        const errors = getAlertFormValidationErrors(
            { ...finishedAlert, name: 'Renamed', forecast_config: { ...savedForecastConfig, ...patch } },
            { savedTargetDate }
        )
        expect(errors).toEqual({})
    })

    // Regrouping the insight to a finer bucket can push a saved date past the point limit, which the
    // server still checks, so the form has to name it instead of letting the save fail.
    it('blocks an unchanged date that no longer fits the insight interval', () => {
        const targetDate = dayjs().add(60, 'day').format('YYYY-MM-DD')
        const errors = getAlertFormValidationErrors(
            { ...finishedAlert, forecast_config: { ...savedForecastConfig, target_date: targetDate } },
            { savedTargetDate: targetDate, insightInterval: 'hour' }
        )
        expect(errors.forecast_config).toBe(
            'This interval needs more than 250 forecast points. Use a coarser insight interval.'
        )
    })

    // The scheduler disables an expired target alert, so turning one back on has to reach a future
    // date. The server rejects that save, so the form has to name it first.
    it('blocks turning an expired alert back on with its old date', () => {
        const errors = getAlertFormValidationErrors(
            { ...finishedAlert, enabled: true },
            { savedTargetDate, savedEnabled: false }
        )
        expect(errors.forecast_config).toBe('The target date must be in the future.')
    })

    it('still saves an expired alert that stays turned off', () => {
        const errors = getAlertFormValidationErrors(
            { ...finishedAlert, enabled: false, name: 'Renamed' },
            { savedTargetDate, savedEnabled: false }
        )
        expect(errors).toEqual({})
    })

    it('still saves an expired alert that was already on', () => {
        const errors = getAlertFormValidationErrors(
            { ...finishedAlert, enabled: true, name: 'Renamed' },
            { savedTargetDate, savedEnabled: true }
        )
        expect(errors).toEqual({})
    })

    it('blocks when the edit moves the date into the past, which the server also rejects', () => {
        const errors = getAlertFormValidationErrors(
            { ...finishedAlert, forecast_config: { ...savedForecastConfig, target_date: '2021-01-01' } },
            { savedTargetDate }
        )
        expect(errors.forecast_config).toBe('The target date must be in the future.')
    })
})

describe('a target alert with no target', () => {
    it('blocks the save and names the field, rather than failing at the server', () => {
        const errors = getAlertFormValidationErrors({
            ...baseAlert,
            forecast_config: {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target: Number.NaN,
                target_direction: ForecastTargetDirection.AT_MOST,
                target_date: dayjs().add(30, 'day').format('YYYY-MM-DD'),
            },
        })
        expect(errors.forecast_config).toBe('Enter a target value')
    })

    it('blocks the save when the target date is cleared', () => {
        const errors = getAlertFormValidationErrors({
            ...baseAlert,
            forecast_config: {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target: 100,
                target_direction: ForecastTargetDirection.AT_MOST,
                target_date: '',
            },
        })

        expect(errors.forecast_config).toBe('Choose a target date')
    })
})
