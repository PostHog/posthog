import { shouldRedirectFromBillingAlerts } from './BillingSection'

describe('billing alerts feature flag routing', () => {
    it('waits for feature flags before redirecting an alerts deep link', () => {
        expect(shouldRedirectFromBillingAlerts('/organization/billing/alerts', false, false)).toBe(false)
        expect(shouldRedirectFromBillingAlerts('/organization/billing/alerts', true, false)).toBe(true)
        expect(shouldRedirectFromBillingAlerts('/organization/billing/alerts', true, true)).toBe(false)
    })
})
