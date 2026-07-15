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
    // testDir is the repo root so we can discover tests in two locations:
    //   - playwright/e2e/**           — cross-cutting and platform-level tests
    //   - products/*/frontend/e2e/**  — product-owned tests, co-located with the product
    // testMatch keeps discovery scoped to those two roots so we don't accidentally
    // pick up unrelated *.spec.ts files (e.g. Jest unit tests under products/).
    testDir: '..',
    testMatch: ['playwright/e2e/**/*.spec.ts', 'products/*/frontend/e2e/**/*.spec.ts'],
    /*
        Maximum time one test can run for. 
        Shorter timeout in local dev since it's annoying to wait 90 seconds for a test to run.
    */
    timeout: process.env.CI ? 90 * 1000 : 50 * 1000,
    expect: {
        /**
         * Maximum time expect() should wait for the condition to be met.
         * For example in `await expect(locator).toHaveText();`
         */
        timeout: process.env.CI ? 40 * 1000 : 10 * 1000,
        toHaveScreenshot: {
            maxDiffPixelRatio: 0.01, // 1% threshold for full-page screenshots
        },
    },
    /* Run tests in files in parallel */
    fullyParallel: true,
    /* Fail the build on CI if you accidentally left test.only in the source code. */
    forbidOnly: !!process.env.CI,
    /*
        Retries are 3 on CI by default (when PLAYWRIGHT_RETRIES is unset). The CI
        Playwright workflow and the nightly flake-audit both set PLAYWRIGHT_RETRIES=0
        to surface the true per-test failure rate for Trunk quarantining, which a
        retry budget otherwise hides (50%-flaky tests pass 93.75% of the time with
        4 attempts).
     */
    retries: process.env.PLAYWRIGHT_RETRIES ? Number(process.env.PLAYWRIGHT_RETRIES) : process.env.CI ? 3 : 2,
    /*
        GitHub Actions has 4 cores so run 3 workers 
        and leave one core for all the rest
        For local running, our machines are all M3 or M4 by now so we can afford to run more workers
    */
    workers: process.env.CI ? 3 : 6,
    /* Reporter to use. See https://playwright.dev/docs/test-reporters */
    reporter: [
        ['html', { open: 'never' }],
        ...(process.env.CI ? [['junit', { outputFile: 'junit-results.xml' }] as const] : []),
        ...(process.env.CI ? [['json', { outputFile: 'results.json' }] as const] : []),
    ],
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

    /* Configure centralized screenshot directory */
    snapshotDir: './__snapshots__',

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
