import { defineConfig, devices } from '@playwright/test'

import { MOCK_APP_PORT } from '../frontend/bin/mockApp.mjs'

const baseURL = `http://localhost:${MOCK_APP_PORT}`

/**
 * Specs against the mock app: a Vite build of the app with mocked API responses, which needs no
 * backend (`pnpm --filter=@posthog/frontend preview:mock-app`). It shares the plugins and module
 * resolution of the app's Vite build, but not its import map or preload lists.
 */
export default defineConfig({
    testDir: './mock-app',
    timeout: 3 * 60 * 1000,
    expect: { timeout: 30 * 1000 },
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 1 : 0,
    reporter: [['html', { open: 'never' }], ['list']],
    use: {
        baseURL,
        trace: 'on-first-retry',
        testIdAttribute: 'data-attr',
        screenshot: 'only-on-failure',
        viewport: { width: 1440, height: 900 },
    },
    webServer: {
        command: 'pnpm --filter=@posthog/frontend preview:mock-app',
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 10 * 60 * 1000,
    },
    projects: [
        { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
        { name: 'webkit', use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 900 } } },
    ],
})
