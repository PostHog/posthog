import { Region } from '~/types'

import { canLogInAsFromCurrentOrigin, getUserAdminUrl, getUserLogInAsUrl } from './userAdmin'

const ADMIN_URL_CASES: [Region.US | Region.EU, string, string, boolean][] = [
    [Region.US, 'https://us.posthog.com', 'https://us.posthog.com', true],
    [Region.EU, 'https://us.posthog.com', 'https://eu.posthog.com', false],
    [Region.US, 'https://eu.posthog.com', 'https://us.posthog.com', false],
    [Region.EU, 'https://eu.posthog.com', 'https://eu.posthog.com', true],
    [Region.US, 'https://app.posthog.com', 'https://us.posthog.com', true],
    [Region.EU, 'https://app.posthog.com', 'https://eu.posthog.com', false],
    [Region.US, 'http://localhost:8011', 'http://localhost:8011', true],
    [Region.EU, 'https://app.dev.posthog.dev', 'https://app.dev.posthog.dev', true],
]

describe('userAdmin', () => {
    test.each(ADMIN_URL_CASES)(
        'opens %s users from %s in %s admin',
        (region, currentOrigin, expectedAdminOrigin, canLogInAs) => {
            expect(getUserAdminUrl(region, 42, currentOrigin)).toBe(
                `${expectedAdminOrigin}/admin/posthog/user/42/change/`
            )
            expect(getUserLogInAsUrl(region, 42, currentOrigin)).toBe(
                `${expectedAdminOrigin}/admin/console/users/42/log-in-as/log-in/`
            )
            expect(canLogInAsFromCurrentOrigin(region, currentOrigin)).toBe(canLogInAs)
        }
    )
})
