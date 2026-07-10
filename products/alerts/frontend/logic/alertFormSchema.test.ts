import { AlertCalculationInterval, AlertConditionType, InsightThresholdType } from '~/queries/schema/schema-general'
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

    it('skips threshold bounds when detector_config is set', () => {
        expect(
            getAlertFormValidationErrors({
                ...baseAlert,
                detector_config: { type: 'zscore', threshold: 3 },
                threshold: {
                    configuration: {
                        type: InsightThresholdType.ABSOLUTE,
                        bounds: {},
                    },
                },
            })
        ).toEqual({})
    })
})
