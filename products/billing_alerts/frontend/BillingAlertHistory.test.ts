import type {
    BillingAlertConfigurationApi,
    BillingAlertEventApi,
} from 'products/billing/frontend/generated/api.schemas'

import { eventValue, historyPoint, wouldFire } from './BillingAlertHistory'

function alert(thresholdType: BillingAlertConfigurationApi['threshold_type']): BillingAlertConfigurationApi {
    return {
        threshold_type: thresholdType,
        threshold_percentage: '50',
        threshold_value: '100',
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

    it('classifies a complete value that clears the threshold', () => {
        expect(wouldFire(alert('relative_increase'), event({ current_value: '150' }))).toBe(true)
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
