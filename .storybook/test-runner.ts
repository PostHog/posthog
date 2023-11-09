import { toMatchImageSnapshot } from 'jest-image-snapshot'
import { getStoryContext, TestRunnerConfig, TestContext } from '@storybook/test-runner'
import type { Locator, Page, LocatorScreenshotOptions } from 'playwright-core'
import type { Mocks } from '~/mocks/utils'
import { StoryContext } from '@storybook/types'

// 'firefox' is technically supported too, but as of June 2023 it has memory usage issues that make is unusable
type SupportedBrowserName = 'chromium' | 'webkit'

// Extend Storybook interface `Parameters` with Chromatic parameters
declare module '@storybook/types' {
    interface Parameters {
        options?: any
        layout?: 'padded' | 'fullscreen' | 'centered'
        testOptions?: {
            /**
             * Whether the test should be a no-op (doesn't jest.skip as @storybook/test-runner doesn't allow that).
             * @default false
             */
            skip?: boolean
            /**
             * Whether we should wait for all loading indicators to disappear before taking a snapshot.
             * @default true
             */
            waitForLoadersToDisappear?: boolean
            /** If set, we'll wait for the given selector to be satisfied. */
            waitForSelector?: string
            /**
             * Whether navigation (sidebar + topbar) should be excluded from the snapshot.
             * Warning: Fails if enabled for stories in which navigation is not present.
             * @default false
             */
            excludeNavigationFromSnapshot?: boolean
            /**
             * The test will always run for all the browers, but snapshots are only taken in Chromium by default.
             * Override this to take snapshots in other browsers too.
             *
             * @default ['chromium']
             */
            snapshotBrowsers?: SupportedBrowserName[]
            /** If taking a component snapshot, you can narrow it down by specifying the selector. */
            snapshotTargetSelector?: string
        }
        msw?: {
            mocks?: Mocks
        }
        [name: string]: any
    }
}

const RETRY_TIMES = 5
const LOADER_SELECTORS = [
    '.ant-skeleton',
    '.Spinner',
    '.LemonSkeleton',
    '.LemonTableLoader',
    '[aria-busy="true"]',
    '[aria-label="Content is loading..."]',
    '.SessionRecordingPlayer--buffering',
    '.Lettermark--unknown',
]

const customSnapshotsDir = `${process.cwd()}/frontend/__snapshots__`

const TEST_TIMEOUT_MS = 10000
const BROWSER_DEFAULT_TIMEOUT_MS = 9000 // Reduce the default timeout down from 30s, to pre-empt Jest timeouts
const SCREENSHOT_TIMEOUT_MS = 9000

module.exports = {
    setup() {
        expect.extend({ toMatchImageSnapshot })
        jest.retryTimes(RETRY_TIMES, { logErrorsBeforeRetry: true })
        jest.setTimeout(TEST_TIMEOUT_MS)
    },
    async postRender(page, context) {
        const browserContext = page.context()
        const storyContext = (await getStoryContext(page, context)) as StoryContext
        const { skip = false, snapshotBrowsers = ['chromium'] } = storyContext.parameters?.testOptions ?? {}

        browserContext.setDefaultTimeout(BROWSER_DEFAULT_TIMEOUT_MS)
        if (!skip) {
            const currentBrowser = browserContext.browser()!.browserType().name() as SupportedBrowserName
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
    const {
        waitForLoadersToDisappear = true,
        waitForSelector,
        excludeNavigationFromSnapshot = false,
    } = storyContext.parameters?.testOptions ?? {}

    let check: (
        page: Page,
        context: TestContext,
        browser: SupportedBrowserName,
        targetSelector?: string
    ) => Promise<void>
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
    await page.waitForSelector('.sb-show-preparing-story', { state: 'detached' })
    await page.evaluate(() => {
        // Stop all animations for consistent snapshots
        document.body.classList.add('storybook-test-runner')
    })
    if (waitForLoadersToDisappear) {
        await Promise.all(LOADER_SELECTORS.map((selector) => page.waitForSelector(selector, { state: 'detached' })))
    }
    if (waitForSelector) {
        await page.waitForSelector(waitForSelector)
    }

    await page.waitForTimeout(400) // Wait for animations to finish

    // Wait for all images to load
    await page.waitForFunction(() =>
        Array.from(document.querySelectorAll('img')).every((i: HTMLImageElement) => i.complete)
    )

    await check(page, context, browser, storyContext.parameters?.testOptions?.snapshotTargetSelector)
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
    await page.evaluate(() => {
        // The screenshot gets clipped by the overflow hidden of the sidebar
        document.querySelector('.SideBar')?.setAttribute('style', 'overflow: visible;')
    })

    await expectLocatorToMatchStorySnapshot(page.locator('.main-app-content'), context, browser)
}

async function expectStoryToMatchComponentSnapshot(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName,
    targetSelector: string = '#storybook-root'
): Promise<void> {
    await page.evaluate(() => {
        const rootEl = document.getElementById('storybook-root')
        if (!rootEl) {
            throw new Error('Could not find root element')
        }
        // Make the root element (which is the default screenshot reference) hug the component
        rootEl.style.display = 'inline-block'
        // If needed, expand the root element so that all popovers are visible in the screenshot
        document.querySelectorAll('.Popover').forEach((popover) => {
            const currentRootBoundingClientRect = rootEl.getBoundingClientRect()
            const popoverBoundingClientRect = popover.getBoundingClientRect()
            if (popoverBoundingClientRect.right > currentRootBoundingClientRect.right) {
                rootEl.style.width = `${popoverBoundingClientRect.right}px`
            }
            if (popoverBoundingClientRect.bottom > currentRootBoundingClientRect.bottom) {
                rootEl.style.height = `${popoverBoundingClientRect.bottom}px`
            }
            if (popoverBoundingClientRect.top < currentRootBoundingClientRect.top) {
                rootEl.style.height = `${-popoverBoundingClientRect.top + currentRootBoundingClientRect.bottom}px`
            }
            if (popoverBoundingClientRect.left < currentRootBoundingClientRect.left) {
                rootEl.style.width = `${-popoverBoundingClientRect.left + currentRootBoundingClientRect.right}px`
            }
        })
        // Make the body transparent to take the screenshot without background
        document.body.style.background = 'transparent'
    })

    await expectLocatorToMatchStorySnapshot(page.locator(targetSelector), context, browser, { omitBackground: true })
}

async function expectLocatorToMatchStorySnapshot(
    locator: Locator | Page,
    context: TestContext,
    browser: SupportedBrowserName,
    options?: LocatorScreenshotOptions
): Promise<void> {
    const image = await locator.screenshot({ timeout: SCREENSHOT_TIMEOUT_MS, ...options })
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
        // 0.01 would be a 1% difference
        failureThreshold: 0.01,
        failureThresholdType: 'percent',
    })
}
