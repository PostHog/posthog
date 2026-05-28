import '@playwright/test'

import { urls } from 'scenes/urls'

import { LOGIN_PASSWORD, LOGIN_USERNAME, test as coreTest } from './playwright-test-core'

/**
 * Legacy Playwright test base with automatic login against the shared demo team.
 *
 * @deprecated New tests should use `workspace-test-base.ts`, which creates a
 * dedicated workspace per test via the setup_test endpoint. The legacy base shares
 * a single team across every spec that imports it, so any insight/cohort/survey/etc.
 * created by one test is visible to the others — the four CI Playwright workers
 * compound this into nondeterministic failures based on ordering.
 *
 * Migration plan:
 * 1. For each spec on this base, decide if it depends on demo-team seed data
 *    (grep for `is_demo`, `Test-Cohort`, `CohortPage`, hardcoded demo references).
 * 2. If yes: the seed needs to be migrated into setup_test fixtures before the
 *    spec can move. Known seed-dependent specs at time of writing:
 *      - playwright/e2e/surveys/crud.spec.ts (uses `is_demo` person property)
 *      - playwright/e2e/product-analytics/cohorts.spec.ts (uses Test-Cohort fixtures)
 * 3. If no: swap the import to `./workspace-test-base` and call
 *    `playwrightSetup.createWorkspace()` + `playwrightSetup.login()` explicitly.
 *
 * Endgame is deleting this file. Tracked under Phase 4.5 of the suite cleanup.
 */
export const test = coreTest.extend<{ loginBeforeTests: void }>({
    // this auto fixture makes sure we log in before every test (maintains legacy behavior)
    loginBeforeTests: [
        async ({ page }, use) => {
            // Perform authentication via API
            await page.request.post('/api/login/', {
                data: {
                    email: LOGIN_USERNAME,
                    password: LOGIN_PASSWORD,
                },
            })
            await page.goto(urls.projectRoot())

            // Continue with tests
            // eslint-disable-next-line react-hooks/rules-of-hooks
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

// Re-export everything for backwards compatibility
export { expect } from '@playwright/test'
export { LOGIN_USERNAME, LOGIN_PASSWORD } from './playwright-test-core'
