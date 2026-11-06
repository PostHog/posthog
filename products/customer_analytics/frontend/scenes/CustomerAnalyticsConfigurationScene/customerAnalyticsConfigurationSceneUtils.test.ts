import { getConfigurationBackTarget } from './customerAnalyticsConfigurationSceneUtils'

describe('getConfigurationBackTarget', () => {
    test.each([
        ['/customer_analytics/accounts/account-1?tab=notes', 'Account'],
        ['/customer_analytics/dashboard', 'Customer analytics'],
    ])('returns to %s', (returnTo, name) => {
        expect(getConfigurationBackTarget(returnTo)).toMatchObject({ path: returnTo, name })
    })

    test.each([undefined, '', '/settings/project', 'https://example.com/customer_analytics/', '//example.com'])(
        'falls back to the breadcrumb for %p',
        (returnTo) => {
            expect(getConfigurationBackTarget(returnTo)).toBeNull()
        }
    )
})
