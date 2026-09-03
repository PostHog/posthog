import { Region } from '~/types'

import { getAccountRelatedUserAdminUrl } from './accountRelatedUserAdminUrl'

const ADMIN_URL_CASES: [Region.US | Region.EU, string, string][] = [
    [Region.US, 'https://us.posthog.com', 'https://us.posthog.com'],
    [Region.EU, 'https://us.posthog.com', 'https://eu.posthog.com'],
    [Region.US, 'http://localhost:8011', 'http://localhost:8011'],
    [Region.EU, 'https://app.dev.posthog.dev', 'https://app.dev.posthog.dev'],
]

describe('getAccountRelatedUserAdminUrl', () => {
    test.each(ADMIN_URL_CASES)('opens %s users from %s in %s admin', (region, currentOrigin, expectedAdminOrigin) => {
        expect(getAccountRelatedUserAdminUrl(region, 42, currentOrigin)).toBe(
            `${expectedAdminOrigin}/admin/posthog/user/42/change/`
        )
    })
})
