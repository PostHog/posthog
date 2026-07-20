import { eventValue, wouldFire } from './BillingAlertHistory'
import type { BillingAlertConfigurationApi, BillingAlertEventApi } from './generated/api.schemas'

function alert(
    thresholdType: BillingAlertConfigurationApi['threshold_type'],
    minimumValue = '0'
): BillingAlertConfigurationApi {
    return {
        threshold_type: thresholdType,
        threshold_percentage: '50',
        threshold_value: '100',
        minimum_value: minimumValue,
    } as BillingAlertConfigurationApi
}

function event(overrides: Partial<BillingAlertEventApi>): BillingAlertEventApi {
    return {
        current_value: '150',
        absolute_delta: '100',
        relative_delta_percentage: '75',
        ...overrides,
    } as BillingAlertEventApi
}

describe('billing alert history classification', () => {
    it('does not chart missing values as zero', () => {
        expect(eventValue(alert('relative_increase'), event({ relative_delta_percentage: null }))).toBeNull()
        expect(eventValue(alert('absolute_value'), event({ current_value: null }))).toBeNull()
    })

    it('does not classify an incomplete baseline as firing', () => {
        expect(
            wouldFire(
                { ...alert('absolute_increase'), threshold_value: '0' },
                event({ current_value: '150', absolute_delta: null })
            )
        ).toBe(false)
    })

    it.each([
        ['relative_increase', { current_value: '99', relative_delta_percentage: '500' }],
        ['absolute_value', { current_value: '99' }],
        ['absolute_increase', { current_value: '99', absolute_delta: '500' }],
    ] as const)('applies the minimum current value to %s alerts', (thresholdType, values) => {
        expect(wouldFire(alert(thresholdType, '100'), event(values))).toBe(false)
    })

    it('classifies a complete value that clears both gates', () => {
        expect(wouldFire(alert('relative_increase', '100'), event({ current_value: '150' }))).toBe(true)
    })
})
