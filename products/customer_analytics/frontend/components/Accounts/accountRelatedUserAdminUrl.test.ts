import { Region } from '~/types'

import {
    getAccountRelatedUserAdminUrl,
    getAccountUserAdminSearchUrl,
    getAccountUserRegion,
} from './accountRelatedUserAdminUrl'

const ADMIN_URL_CASES: [Region.US | Region.EU, string, string][] = [
    [Region.US, 'https://us.posthog.com', 'https://us.posthog.com'],
    [Region.EU, 'https://us.posthog.com', 'https://eu.posthog.com'],
    [Region.US, 'http://localhost:8011', 'http://localhost:8011'],
    [Region.EU, 'https://app.dev.posthog.dev', 'https://app.dev.posthog.dev'],
]

const INSTANCE_URL_CASES: [unknown, Region.US | Region.EU][] = [
    ['https://eu.posthog.com', Region.EU],
    ['https://us.posthog.com', Region.US],
    [null, Region.US],
]

describe('accountRelatedUserAdminUrl', () => {
    test.each(ADMIN_URL_CASES)('opens %s users from %s in %s admin', (region, currentOrigin, expectedAdminOrigin) => {
        expect(getAccountRelatedUserAdminUrl(region, 42, currentOrigin)).toBe(
            `${expectedAdminOrigin}/admin/posthog/user/42/change/`
        )
    })
    test.each(INSTANCE_URL_CASES)('reads instance URL %s as %s', (instanceUrl, expectedRegion) => {
        expect(getAccountUserRegion(instanceUrl)).toBe(expectedRegion)
    })

    test.each(ADMIN_URL_CASES)(
        'searches %s users from %s in %s admin',
        (region, currentOrigin, expectedAdminOrigin) => {
            expect(getAccountUserAdminSearchUrl(region, 'jane+test@example.com', currentOrigin)).toBe(
                `${expectedAdminOrigin}/admin/posthog/user/?q=jane%2Btest%40example.com`
            )
        }
    )
})
