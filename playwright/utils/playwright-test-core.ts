import { Page, test as base } from '@playwright/test'

import { Identifier, Navigation } from './navigation'

export const LOGIN_USERNAME = process.env.LOGIN_USERNAME || 'test@posthog.com'
export const LOGIN_PASSWORD = process.env.LOGIN_PASSWORD || '12345678'

declare module '@playwright/test' {
    interface Page {
        goToMenuItem(name: string): Promise<void>
    }
}

/**
 * Core Playwright test base with page extensions but NO automatic login
 * Use this as the foundation for workspace-based tests
 */
export const test = base.extend<{ page: Page }>({
    page: async ({ page }, use) => {
        // Add custom methods to the page object
        page.goToMenuItem = async function (name: Identifier): Promise<void> {
            await new Navigation(page).openMenuItem(name)
        }

        // Pass the extended page to the test
        // eslint-disable-next-line react-hooks/rules-of-hooks
        await use(page)
    },
})

export { expect } from '@playwright/test'
