import { defineConfig, devices } from '@playwright/test'

/**
 * Read environment variables from file.
 * https://github.com/motdotla/dotenv
 */
// require('dotenv').config();

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
    testDir: './playwright',
    /* Maximum time one test can run for. */
    timeout: 30 * 1000,
    expect: {
        /**
         * Maximum time expect() should wait for the condition to be met.
         * For example in `await expect(locator).toHaveText();`
         */
        timeout: 5000,
    },
    /* Run tests in files in parallel */
    fullyParallel: true,
    /* Fail the build on CI if you accidentally left test.only in the source code. */
    forbidOnly: !!process.env.CI,
    /* Retry on CI only */
    retries: process.env.CI ? 2 : 0,
    /* Run one worker per core in GitHub Actions. */
    workers: process.env.CI ? 4 : undefined,
    /* Reporter to use. See https://playwright.dev/docs/test-reporters */
    reporter: [['html', { open: 'never' }]],
    /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
    use: {
        /* Maximum time each action such as `click()` can take. Defaults to 0 (no limit). */
        actionTimeout: 0,
        /* Base URL to use in actions like `await page.goto('/')`. */
        // baseURL: 'http://localhost:3000',

        /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
        trace: 'on-first-retry',
    },

    /* Configure projects for major browsers */
    projects: [
        {
            name: 'chromium',
            use: {
                // ...devices['Desktop Chrome'],
                launchOptions: {
                    args: [
                        '--disable-gpu',
                        '--no-sandbox',
                        '--disable-infobars',
                        '--hide-scrollbars',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-skia-runtime-opt',
                        '--font-render-hinting=none',
                        '--run-all-compositor-stages-before-draw',
                        '--disable-new-content-rendering-timeout',
                        '--disable-threaded-animation',
                        '--disable-threaded-scrolling',
                        '--disable-checker-imaging',
                        '--disable-image-animation-resync',
                        '--disable-features=PaintHolding',
                        '--disable-partial-raster',
                        '--in-process-gpu',
                        '--use-gl=swiftshader',
                        '--force-color-profile=srgb',
                        '--force-device-scale-factor=1',
                        '--single-process',
                        '--disable-background-timer-throttling',
                        '--disable-backgrounding-occluded-windows',
                        '--disable-hang-monitor',
                        '--disable-ipc-flooding-protection',
                        '--disable-renderer-backgrounding',
                        '--disable-background-networking',
                        '--disable-breakpad',
                        '--disable-component-update',
                        '--disable-domain-reliability',
                        '--disable-sync',
                        '--disable-font-subpixel-positioning',
                        '--disable-lcd-text',
                    ],
                },
            },
        },

        // {
        //   name: 'firefox',
        //   use: {
        //     ...devices['Desktop Firefox'],
        //   },
        // },

        // {
        //   name: 'webkit',
        //   use: {
        //     ...devices['Desktop Safari'],
        //   },
        // },

        /* Test against mobile viewports. */
        // {
        //   name: 'Mobile Chrome',
        //   use: {
        //     ...devices['Pixel 5'],
        //   },
        // },
        // {
        //   name: 'Mobile Safari',
        //   use: {
        //     ...devices['iPhone 12'],
        //   },
        // },

        /* Test against branded browsers. */
        // {
        //   name: 'Microsoft Edge',
        //   use: {
        //     channel: 'msedge',
        //   },
        // },
        // {
        //   name: 'Google Chrome',
        //   use: {
        //     channel: 'chrome',
        //   },
        // },
    ],

    /* Folder for test artifacts such as screenshots, videos, traces, etc. */
    // outputDir: 'test-results/',

    /* Run your local dev server before starting the tests */
    // webServer: {
    //   command: 'npm run start',
    //   port: 3000,
    // },
})
