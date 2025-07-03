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
    testDir: '.',
    /* 
        Maximum time one test can run for. 
        Shorter timeout in local dev since it's annoying to wait 90 seconds for a test to run.
    */
    timeout: process.env.CI ? 60 * 1000 : 30 * 1000,
    expect: {
        /**
         * Maximum time expect() should wait for the condition to be met.
         * For example in `await expect(locator).toHaveText();`
         */
        timeout: process.env.CI ? 40 * 1000 : 10 * 1000,
    },
    /* Run tests in files in parallel */
    fullyParallel: true,
    /* Fail the build on CI if you accidentally left test.only in the source code. */
    forbidOnly: !!process.env.CI,
    /* Retry on CI only */
    retries: process.env.CI ? 3 : 2,
    /* 
        GitHub Actions has 4 cores so run 3 workers 
        and leave one core for all the rest
        For local running, our machines are all M3 or M4 by now so we can afford to run more workers
    */
    workers: process.env.CI ? 3 : 6,
    /* Reporter to use. See https://playwright.dev/docs/test-reporters */
    reporter: [['html', { open: 'never' }]],
    /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
    use: {
        /* Maximum time each action such as `click()` can take. Defaults to 0 (no limit). */
        actionTimeout: 0,
        /* Base URL to use in actions like `await page.goto('/')`. */
        baseURL: process.env.CI ? 'http://localhost:8000' : process.env.BASE_URL || 'http://localhost:8080',

        /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
        trace: 'on-first-retry',

        /* Locate elements defined by `data-attr-something` with `page.getByTestId('something')` */
        testIdAttribute: 'data-attr',

        screenshot: 'only-on-failure',
    },

    /* Configure projects for major browsers */
    projects: [
        {
            name: 'chromium',
            use: { ...devices['Desktop Chrome'] },
        },
        // {
        //     name: 'chromium',
        //     use: {
        //         ...devices['Desktop Chrome'],
        //         launchOptions: {
        //             // https://github.com/GoogleChrome/chrome-launcher/blob/main/docs/chrome-flags-for-tools.md
        //             args: [
        //                 '--headless=new',
        //                 '--single-process',
        //
        //                 '--allow-pre-commit-input',
        //                 '--deterministic-mode',
        //                 '--disable-features=PaintHolding',
        //                 '--disable-partial-raster',
        //                 '--disable-skia-runtime-opt',
        //                 '--disable-gpu',
        //                 '--use-gl=swiftshader',
        //                 '--force-color-profile=srgb',
        //             ],
        //         },
        //     },
        // },

        // {
        //   name: 'firefox',
        //   use: {
        //     ...devices['Desktop Firefox'],
        //   },
        // },

        // {
        //     name: 'webkit',
        //     use: {
        //         ...devices['Desktop Safari'],
        //     },
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
