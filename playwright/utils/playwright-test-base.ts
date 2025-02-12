import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

import { expect, Page, test as base } from '@playwright/test'
import { urls } from 'scenes/urls'

declare module '@playwright/test' {
    interface Page {
        // resetCapturedEvents(): Promise<void>
        //
        // capturedEvents(): Promise<CaptureResult[]>
        //
        // waitingForNetworkCausedBy: (urlPatterns: (string | RegExp)[], action: () => Promise<void>) => Promise<void>
        //
        // expectCapturedEventsToBe(expectedEvents: string[]): Promise<void>
    }
}

export const test = base.extend<{ loginBeforeTests: void; page: Page }>({
    page: async ({ page }, use) => {
        // // Add custom methods to the page object
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
        async ({ page }, use) => {
            const authFile = resolve('playwright/.auth/user.json')

            mkdirSync(dirname(authFile), { recursive: true }) // Ensure directory exists

            // perform authentication steps
            await page.goto(urls.login())

            // Wait for either login input OR the authenticated UI element
            const loginField = page.getByPlaceholder('email@yourcompany.com')
            const homepageMenuItem = page.locator('[data-attr="menu-item-projecthomepage"]')

            const firstVisible = await Promise.race([
                loginField.waitFor({ timeout: 5000 }).then(() => 'login'),
                homepageMenuItem.waitFor({ timeout: 5000 }).then(() => 'authenticated'),
            ]).catch(() => 'timeout')

            if (firstVisible === 'login') {
                // Not logged in, proceed with login
                await loginField.fill('test@posthog.com')

                const passwd = page.getByPlaceholder('••••••••••')
                await expect(passwd).toBeVisible()
                await passwd.fill('12345678')

                await page.getByRole('button', { name: 'Log in' }).click()

                // Wait for login confirmation
                await homepageMenuItem.waitFor()
            } else if (firstVisible === 'timeout') {
                throw new Error('Neither login page nor authenticated UI loaded')
            }

            // Save auth state
            await page.context().storageState({ path: authFile })

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
