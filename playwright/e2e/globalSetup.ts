// import { chromium, FullConfig } from '@playwright/test'
// import { request } from '@playwright/test'

// async function globalSetup(config: FullConfig): Promise<void> {
//     // TODO: we should have a stored state for logged in and premium users

//     // Approach 1: use request to login
//     // https://playwright.dev/docs/auth#sign-in-via-api-request
//     const { baseURL, storageState } = config.projects[0].use
//     const requestContext = await request.newContext({ baseURL })

//     await requestContext.post('/api/login', {
//         form: {
//             email: 'test@posthog.com',
//             password: '12345678',
//         },
//     })

//     // Save signed-in state to 'state.json'.
//     await requestContext.storageState({ path: storageState as string })
//     await requestContext.dispose()

//     // Approach 2: use automation to login
//     // https://playwright.dev/docs/auth#reuse-signed-in-state
//     const { baseURL, storageState } = config.projects[0].use

//     const browser = await chromium.launch()
//     const context = await browser.newContext()
//     const page = await browser.newPage()

//     try {
//         await context.tracing.start({ screenshots: true, snapshots: true })

//         // perform login
//         await page.goto(baseURL)
//         await page.getByTestId('login-email').fill('test@posthog.com')
//         await page.getByRole('button', { name: 'Login' }).click()
//         await page.getByTestId('password').fill('12345678')
//         await page.getByRole('button', { name: 'Login' }).click()

//         await context.storageState({ path: storageState as string })
//         await context.tracing.stop({
//             path: './test-results/setup-trace.zip',
//         })
//         await page.close()
//     } catch (error) {
//         // display with `npx playwright show-trace test-results/failed-setup-trace.zip`
//         await context.tracing.stop({
//             path: './test-results/failed-setup-trace.zip',
//         })
//         await page.close()
//         throw error
//     }
// }

// export default globalSetup

export default async function globalSetup(): Promise<void> {}
