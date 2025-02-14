import { expect, Page, test as base } from '@playwright/test'
import { urls } from 'scenes/urls'
import { AppContext } from '~/types'

export const LOGIN_USERNAME = process.env.LOGIN_USERNAME || 'test@posthog.com'
export const LOGIN_PASSWORD = process.env.LOGIN_PASSWORD || '12345678'

export type WindowWithPostHog = typeof globalThis & {
    POSTHOG_APP_CONTEXT: AppContext
}

declare module '@playwright/test' {
    interface Page {
        setAppContext<K extends keyof AppContext>(key: K, value: AppContext[K]): Promise<void>
        // resetCapturedEvents(): Promise<void>
        //
        // capturedEvents(): Promise<CaptureResult[]>
        //
        // waitingForNetworkCausedBy: (urlPatterns: (string | RegExp)[], action: () => Promise<void>) => Promise<void>
        //
        // expectCapturedEventsToBe(expectedEvents: string[]): Promise<void>
    }
}

let authCookies: any[] = [] // Store cookies in memory
let authStorage: Record<string, string> = {} // Store local/session storage data

/**
 * we override the base playwright test to add things useful to us
 * */
export const test = base.extend<{ loginBeforeTests: void; page: Page }>({
    page: async ({ page }, use) => {
        // // Add custom methods to the page object
        page.setAppContext = async function <K extends keyof AppContext>(key: K, value: AppContext[K]): Promise<void> {
            await page.evaluate(() => {
                ;(window as WindowWithPostHog).POSTHOG_APP_CONTEXT[key] = value
            })
        }
        // page.resetCapturedEvents = async function () {
        //     await this.evaluate(() => {
        //         ;(window as WindowWithPostHog).capturedEvents = []
        //     })
        // }
        // page.capturedEvents = async function () {
        //     return this.evaluate(() => {
        //         return (window as WindowWithPostHog).capturedEvents || []
        //     })
        // }
        // page.waitingForNetworkCausedBy = async function (
        //     urlPatterns: (string | RegExp)[],
        //     action: () => Promise<void>
        // ) {
        //     const responsePromises = urlPatterns.map((urlPattern) => {
        //         return this.waitForResponse(urlPattern)
        //     })
        //
        //     await action()
        //
        //     // eslint-disable-next-line compat/compat
        //     await Promise.allSettled(responsePromises)
        // }
        // page.expectCapturedEventsToBe = async function (expectedEvents: string[]) {
        //     const capturedEvents = await this.capturedEvents()
        //     expect(capturedEvents.map((x) => x.event)).toEqual(expectedEvents)
        // }

        // Pass the extended page to the test
        await use(page)
    },
    // this auto fixture makes sure we log in before every test
    loginBeforeTests: [
        async ({ page, context }, use) => {
            // If we already have auth state, reuse it
            if (authCookies.length > 0) {
                await context.addCookies(authCookies)

                // Restore session/local storage from memory
                await page.goto(urls.login()) // Ensure we're on the right domain
                await page.evaluate((storage) => {
                    for (const [key, value] of Object.entries(storage)) {
                        sessionStorage.setItem(key, value)
                    }
                }, authStorage)
            } else {
                // Perform authentication steps
                await page.goto(urls.login())

                const loginField = page.getByPlaceholder('email@yourcompany.com')
                const homepageMenuItem = page.locator('[data-attr="menu-item-projecthomepage"]')

                const firstVisible = await Promise.race([
                    loginField.waitFor({ timeout: 5000 }).then(() => 'login'),
                    homepageMenuItem.waitFor({ timeout: 5000 }).then(() => 'authenticated'),
                ]).catch(() => 'timeout')

                if (firstVisible === 'login') {
                    await loginField.fill(LOGIN_USERNAME)

                    const passwd = page.getByPlaceholder('••••••••••')
                    await expect(passwd).toBeVisible()
                    await passwd.fill(LOGIN_PASSWORD)

                    await page.getByRole('button', { name: 'Log in' }).click()
                    await homepageMenuItem.waitFor()
                } else if (firstVisible === 'timeout') {
                    throw new Error('Neither login page nor authenticated UI loaded')
                }

                // Store authentication data in memory
                authCookies = await context.cookies()
                authStorage = await page.evaluate(() => {
                    const storage = {}
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const key = sessionStorage.key(i)
                        if (key) {
                            storage[key] = sessionStorage.getItem(key)
                        }
                    }
                    return storage
                })
            }

            // Continue with tests
            await use()

            // any teardown would go here
        },
        { auto: true },
    ],
    // mockStaticAssets: [
    //     async ({ context }, use) => {
    //         // also equivalent of cy.intercept('GET', '/surveys/*').as('surveys') ??
    //         void context.route('**/e/*', (route) => {
    //             void route.fulfill({
    //                 status: 200,
    //                 contentType: 'application/json',
    //                 body: JSON.stringify({ status: 1 }),
    //                 headers: {
    //                     'Access-Control-Allow-Headers': '*',
    //                     'Access-Control-Allow-Origin': '*',
    //                     'Access-Control-Allow-Credentials': 'true',
    //                 },
    //             })
    //         })
    //
    //         void context.route('**/ses/*', (route) => {
    //             void route.fulfill({
    //                 status: 200,
    //                 contentType: 'application/json',
    //                 body: JSON.stringify({ status: 1 }),
    //             })
    //         })
    //
    //         lazyLoadedJSFiles.forEach((key: string) => {
    //             void context.route(new RegExp(`^.*/static/${key}\\.js(\\?.*)?$`), (route) => {
    //                 route.fulfill({
    //                     headers: {
    //                         loaded: 'using relative path by playwright',
    //                     },
    //                     path: `./dist/${key}.js`,
    //                 })
    //             })
    //
    //             void context.route(`**/static/${key}.js.map`, (route) => {
    //                 route.fulfill({
    //                     headers: { loaded: 'using relative path by playwright' },
    //                     path: `./dist/${key}.js.map`,
    //                 })
    //             })
    //         })
    //
    //         await use()
    //         // there's no teardown, so nothing here
    //     },
    //     // auto so that tests don't need to remember they need this... every test needs it
    //     { auto: true },
    // ],
})
export { expect } from '@playwright/test'
