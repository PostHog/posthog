import { Region } from '~/types'

import { canLogInAsFromCurrentOrigin, getUserAdminUrl, getUserLogInAsUrl } from './userAdmin'

const ADMIN_URL_CASES: [Region.US | Region.EU, string, string][] = [
    [Region.US, 'https://us.posthog.com', 'https://us.posthog.com'],
    [Region.EU, 'https://us.posthog.com', 'https://eu.posthog.com'],
    [Region.US, 'http://localhost:8011', 'http://localhost:8011'],
    [Region.EU, 'https://app.dev.posthog.dev', 'https://app.dev.posthog.dev'],
]

describe('userAdmin', () => {
    test.each(ADMIN_URL_CASES)('opens %s users from %s in %s admin', (region, currentOrigin, expectedAdminOrigin) => {
        expect(getUserAdminUrl(region, 42, currentOrigin)).toBe(`${expectedAdminOrigin}/admin/posthog/user/42/change/`)
        expect(getUserLogInAsUrl(region, 42, currentOrigin)).toBe(
            `${expectedAdminOrigin}/admin/console/users/42/log-in-as/log-in/`
        )
        expect(canLogInAsFromCurrentOrigin(region, currentOrigin)).toBe(currentOrigin === expectedAdminOrigin)
    })
})
