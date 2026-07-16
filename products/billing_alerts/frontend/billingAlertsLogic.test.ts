import type { BillingAlertConfiguration } from './billingAlertsLogic'
import { isBillingAlertHiddenByPausedFilter } from './billingAlertsLogic'

function alert(state: BillingAlertConfiguration['state'], enabled: boolean): BillingAlertConfiguration {
    return { state, enabled } as BillingAlertConfiguration
}

describe('billing alert paused filter', () => {
    it('keeps broken auto-disabled alerts visible', () => {
        expect(isBillingAlertHiddenByPausedFilter(alert('broken', false), false)).toBe(false)
    })

    it('hides other disabled alerts unless paused alerts are requested', () => {
        const paused = alert('not_firing', false)

        expect(isBillingAlertHiddenByPausedFilter(paused, false)).toBe(true)
        expect(isBillingAlertHiddenByPausedFilter(paused, true)).toBe(false)
    })
})
