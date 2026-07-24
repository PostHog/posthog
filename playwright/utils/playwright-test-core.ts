import { Page, test as base } from '@playwright/test'

import { decideForTest, loadActiveEntries } from '../playwright.quarantine'
import { Identifier, Navigation } from './navigation'

// Read once per worker; a `mode: "skip"` match short-circuits the test below.
// `mode: "run"` is enforced separately by playwright.quarantine.reporter.ts.
const quarantineEntries = loadActiveEntries()

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
export const test = base.extend<{ page: Page; _quarantine: void }>({
    page: async ({ page }, use) => {
        // Add custom methods to the page object
        page.goToMenuItem = async function (name: Identifier): Promise<void> {
            await new Navigation(page).openMenuItem(name)
        }

        // Pass the extended page to the test
        // eslint-disable-next-line react-hooks/rules-of-hooks
        await use(page)
    },

    // Auto fixture: skip a `mode: "skip"` quarantined test before its body runs.
    // titlePath starts with the file name, so slice(1) is the describe/test name.
    // Skip enforcement rides this base, so a spec must import `test` from here (or
    // a base that extends it), not straight from `@playwright/test`, or its skip
    // entries silently no-op. `mode: "run"` needs no base (the reporter sees all).
    _quarantine: [
        // eslint-disable-next-line no-empty-pattern -- Playwright fixtures require the deps arg; we use none.
        async ({}, use) => {
            if (quarantineEntries.length > 0) {
                const info = test.info()
                const decision = decideForTest(quarantineEntries, info.file, info.titlePath.slice(1))
                if (decision?.mode === 'skip') {
                    // eslint-disable-next-line no-console
                    console.warn(`[quarantine] skipping ${decision.label}`)
                    // eslint-disable-next-line react-hooks/rules-of-hooks
                    test.skip(true, decision.label)
                }
            }
            await use(undefined)
        },
        { auto: true },
    ],
})

export { expect } from '@playwright/test'
