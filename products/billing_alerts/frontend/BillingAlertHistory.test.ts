import { eventValue, historyPoint, wouldFire } from './BillingAlertHistory'
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
        configuration_revision: 2,
    } as unknown as BillingAlertConfigurationApi
}

function event(overrides: Partial<BillingAlertEventApi>): BillingAlertEventApi {
    return {
        current_value: '150',
        absolute_delta: '100',
        relative_delta_percentage: '75',
        kind: 'check',
        created_at: '2026-07-21T08:00:00Z',
        configuration_revision: 2,
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

    it.each(['check', 'errored'] as const)('does not mark %s events as firing edges', (kind) => {
        expect(historyPoint(alert('relative_increase'), event({ kind, state_after: 'firing' }))?.firedAtTime).toBe(
            false
        )
    })

    it('marks only firing events as firing edges', () => {
        expect(historyPoint(alert('relative_increase'), event({ kind: 'firing' }))?.firedAtTime).toBe(true)
    })

    it('classifies against the current rule only for the same configuration revision', () => {
        expect(
            historyPoint(
                alert('relative_increase'),
                event({ configuration_revision: 2 } as Partial<BillingAlertEventApi>)
            )?.wouldFireUnderCurrentConfiguration
        ).toBe(true)
        expect(
            historyPoint(
                alert('relative_increase'),
                event({ configuration_revision: 1 } as Partial<BillingAlertEventApi>)
            )?.wouldFireUnderCurrentConfiguration
        ).toBeNull()
    })
})
