/* eslint-disable react-hooks/rules-of-hooks */
import { Page, test as base } from '@playwright/test'

import { AppContext } from '~/types'

import { Identifier, Navigation } from './navigation'
import { createDisableAnimationsInitScript } from './pagePerformance'

export const LOGIN_USERNAME = process.env.LOGIN_USERNAME || 'test@posthog.com'
export const LOGIN_PASSWORD = process.env.LOGIN_PASSWORD || '12345678'

export type WindowWithPostHog = typeof globalThis & {
    POSTHOG_APP_CONTEXT: AppContext
}

declare module '@playwright/test' {
    interface Page {
        setAppContext<K extends keyof AppContext>(key: K, value: AppContext[K]): Promise<void>
        goToMenuItem(name: string): Promise<void>
    }
}

/**
 * Core Playwright test base with page extensions but NO automatic login
 * Use this as the foundation for both legacy tests and new workspace-based tests
 */
export const test = base.extend<{ page: Page }>({
    // Set up context-level init script BEFORE page fixture
    // This fixture runs before the page fixture because it's defined first
    context: async ({ context }, use) => {
        // Add init script via context to disable animations on all page loads
        // Animations are disabled by default for faster, more reliable tests
        // Opt-out with DISABLE_ANIMATIONS=false if you need to test animations
        if (process.env.DISABLE_ANIMATIONS !== 'false') {
            const disableAnimationsScript = createDisableAnimationsInitScript()
            await context.addInitScript({ content: disableAnimationsScript })
        }
        await use(context)
    },
    page: async ({ page }, use) => {
        // page.on('pageerror', (error) => {
        //     console.error('Playwright page error:', error)
        // })
        // Add custom methods to the page object
        page.setAppContext = async function <K extends keyof AppContext>(key: K, value: AppContext[K]): Promise<void> {
            await page.evaluate(
                ([key, value]) => {
                    const appContext = (window as WindowWithPostHog).POSTHOG_APP_CONTEXT
                    // @ts-expect-error - Type safety is handled by the generic constraint
                    appContext[key] = value
                },
                [key, value]
            )
        }
        page.goToMenuItem = async function (name: Identifier): Promise<void> {
            await new Navigation(page).openMenuItem(name)
        }

        // Pass the extended page to the test
        await use(page)
    },
})

export { expect } from '@playwright/test'
