import { toMatchImageSnapshot } from 'jest-image-snapshot'
import { OptionsParameter } from '@storybook/addons'
import { getStoryContext, TestRunnerConfig, TestContext } from '@storybook/test-runner'
import type { Locator, Page, LocatorScreenshotOptions } from 'playwright-core'
import type { Mocks } from '~/mocks/utils'
import { StoryContext } from '@storybook/react'

type SupportedBrowserName = 'chromium' | 'firefox' | 'webkit'

// Extend Storybook interface `Parameters` with Chromatic parameters
declare module '@storybook/react' {
    interface Parameters {
        options?: OptionsParameter
        layout?: 'padded' | 'fullscreen' | 'centered'
        testOptions?: {
            /**
             * Whether the test should be a no-op (doesn't jest.skip as @storybook/test-runner doesn't allow that).
             * @default false
             */
            skip?: boolean
            /**
             * Whether we should wait for all loading indicators to disappear.
             * Enable for stories that take a bit to load, and which you aren't testing loading states for.
             * @default false
             */
            waitForLoadingToFinish?: boolean
            /**
             * Whether navigation (sidebar + topbar) should be excluded from the snapshot.
             * Warning: Fails if enabled for stories in which navigation is not present.
             */
            excludeNavigationFromSnapshot?: boolean
            /**
             * The test will always run for all the browers, but snapshots are only taken in Chromium by default.
             * Override this to take snapshots in other browsers too.
             * @default ['chromium']
             */
            snapshotBrowsers?: SupportedBrowserName[]
        }
        mockDate?: string | number | Date
        msw?: {
            mocks?: Mocks
        }
        [name: string]: any
    }
}

const RETRY_TIMES = 5

const customSnapshotsDir = `${process.cwd()}/frontend/__snapshots__`

module.exports = {
    setup() {
        expect.extend({ toMatchImageSnapshot })
        jest.retryTimes(RETRY_TIMES, { logErrorsBeforeRetry: true })
    },
    async postRender(page, context) {
        const storyContext = await getStoryContext(page, context)
        const { skip = false, snapshotBrowsers = ['chromium'] } = storyContext.parameters?.testOptions ?? {}

        if (!skip) {
            await page.evaluate(() => {
                // Stop all animations for consistent snapshots
                document.body.classList.add('storybook-test-runner')
            })

            const currentBrowser = page.context().browser()!.browserType().name() as 'chromium' | 'firefox' | 'webkit'
            if (snapshotBrowsers.includes(currentBrowser)) {
                await expectStoryToMatchSnapshot(page, context, storyContext, currentBrowser)
            }
        }
    },
} as TestRunnerConfig

async function expectStoryToMatchSnapshot(
    page: Page,
    context: TestContext,
    storyContext: StoryContext,
    browser: SupportedBrowserName
): Promise<void> {
    const { waitForLoadingToFinish = false, excludeNavigationFromSnapshot = false } =
        storyContext.parameters?.testOptions ?? {}

    let check: (page: Page, context: TestContext, browser: SupportedBrowserName) => Promise<void>
    if (storyContext.parameters?.layout === 'fullscreen') {
        if (excludeNavigationFromSnapshot) {
            check = expectStoryToMatchSceneSnapshot
        } else {
            check = expectStoryToMatchFullPageSnapshot
        }
    } else {
        check = expectStoryToMatchComponentSnapshot
    }
    // Wait for story to load
    await page.waitForSelector('.sb-show-preparing-story', { state: 'detached', timeout: 1000 })
    if (waitForLoadingToFinish) {
        await Promise.all([
            page.waitForSelector('.ant-skeleton', { state: 'detached', timeout: 1000 }),
            page.waitForSelector('.LemonSkeleton', { state: 'detached', timeout: 1000 }),
            page.waitForSelector('.Spinner', { state: 'detached', timeout: 1000 }),
        ])
    }
    await page.waitForTimeout(200) // Just a bit of extra delay for things to settle
    await check(page, context, browser)
}

async function expectStoryToMatchFullPageSnapshot(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName
): Promise<void> {
    await expectLocatorToMatchStorySnapshot(page, context, browser)
}

async function expectStoryToMatchSceneSnapshot(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName
): Promise<void> {
    await expectLocatorToMatchStorySnapshot(page.locator('.main-app-content'), context, browser)
}

async function expectStoryToMatchComponentSnapshot(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName
): Promise<void> {
    await page.evaluate(() => {
        const rootEl = document.getElementById('root')
        if (rootEl) {
            // don't expand the container element to limit the screenshot
            // to the component's size
            rootEl.style.display = 'inline-block'
        }
        // make the body transparent to take the screenshot
        // without background
        document.body.style.background = 'transparent'
    })

    await expectLocatorToMatchStorySnapshot(page.locator('#root'), context, browser, { omitBackground: true })
}

async function expectLocatorToMatchStorySnapshot(
    locator: Locator | Page,
    context: TestContext,
    browser: SupportedBrowserName,
    options?: LocatorScreenshotOptions
): Promise<void> {
    const image = await locator.screenshot({ timeout: 3000, ...options })
    let customSnapshotIdentifier = context.id
    if (browser !== 'chromium') {
        customSnapshotIdentifier += `--${browser}`
    }
    expect(image).toMatchImageSnapshot({
        customSnapshotsDir,
        customSnapshotIdentifier,
        // Compare structural similarity instead of raw pixels - reducing false positives
        // See https://github.com/americanexpress/jest-image-snapshot#recommendations-when-using-ssim-comparison
        comparisonMethod: 'ssim',
        failureThreshold: 0.001,
        failureThresholdType: 'percent',
    })
}
