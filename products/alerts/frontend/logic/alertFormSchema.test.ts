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

    // A target alert carries its own target value, so the threshold bounds row is not shown and must
    // not block saving. Only future_breach reads those bounds.
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

    // A band-deviation forecast scores the actual against the forecast's own uncertainty band, so it
    // has no user-set threshold — bounds must not be required. A future-breach forecast still checks
    // against the threshold bounds below, so it must keep requiring them.
    it.each([
        [ForecastConditionType.BAND_DEVIATION, true],
        [ForecastConditionType.FUTURE_BREACH, false],
    ])('thresholdAlertHasBounds with empty bounds and forecast condition %s is %s', (condition, expected) => {
        expect(
            thresholdAlertHasBounds({
                ...baseAlert,
                forecast_config: {
                    type: 'ForecastConfig',
                    engine: ForecastEngineType.PROPHET,
                    condition,
                },
                threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: {} } },
            })
        ).toBe(expected)
    })
})

describe('a target alert whose date has passed', () => {
    // The server re-checks the target date whenever a request carries a forecast config at all, so
    // the editor has to block on exactly the same trigger. Keying the editor on the date alone let
    // an edit to the target send a stale past date and take a 400 with no field marked.
    const savedForecastConfig = {
        type: 'ForecastConfig' as const,
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.TARGET_BY_DATE,
        target: 100,
        target_direction: ForecastTargetDirection.AT_LEAST,
        target_date: '2020-01-01',
    }
    const finishedAlert: AlertFormType = { ...baseAlert, forecast_config: savedForecastConfig }

    it('saves when nothing about the forecast changed, so it can still be renamed or turned off', () => {
        expect(getAlertFormValidationErrors({ ...finishedAlert, name: 'Renamed' }, { savedForecastConfig })).toEqual({})
    })

    it.each([
        ['the target', { target: 250 }],
        ['the direction', { target_direction: ForecastTargetDirection.AT_MOST }],
        ['the sensitivity', { interval_width: 0.8 }],
    ] as const)('blocks when %s changed, because the server will re-check the date', (_n, patch) => {
        const errors = getAlertFormValidationErrors(
            { ...finishedAlert, forecast_config: { ...savedForecastConfig, ...patch } },
            { savedForecastConfig }
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
                target_direction: ForecastTargetDirection.AT_MOST,
                // Within range, because picking the condition seeds a valid date: the realistic
                // first state is a good date and no target yet.
                target_date: dayjs().add(30, 'day').format('YYYY-MM-DD'),
            },
        })
        expect(errors.forecast_config).toBe('Enter a target value')
    })
})
