import { toMatchImageSnapshot } from 'jest-image-snapshot'
import { getStoryContext, TestRunnerConfig, TestContext, waitForPageReady } from '@storybook/test-runner'
import type { Locator, Page, LocatorScreenshotOptions } from '@playwright/test'
import type { Mocks } from '~/mocks/utils'
import { StoryContext } from '@storybook/csf'

// 'firefox' is technically supported too, but as of June 2023 it has memory usage issues that make is unusable
type SupportedBrowserName = 'chromium' | 'webkit'
type SnapshotTheme = 'legacy' | 'light' | 'dark'

// Extend Storybook interface `Parameters` with Chromatic parameters
declare module '@storybook/types' {
    interface Parameters {
        options?: any
        layout?: 'padded' | 'fullscreen' | 'centered'
        testOptions?: {
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

    interface Globals {
        theme: SnapshotTheme
    }
}

const RETRY_TIMES = 3
const LOADER_SELECTORS = [
    '.ant-skeleton',
    '.Spinner',
    '.LemonSkeleton',
    '.LemonTableLoader',
    '.Toastify__toast-container',
    '[aria-busy="true"]',
    '.SessionRecordingPlayer--buffering',
    '.Lettermark--unknown',
]

const customSnapshotsDir = `${process.cwd()}/frontend/__snapshots__`

const JEST_TIMEOUT_MS = 15000
const PLAYWRIGHT_TIMEOUT_MS = 10000 // Must be shorter than JEST_TIMEOUT_MS

module.exports = {
    setup() {
        expect.extend({ toMatchImageSnapshot })
        jest.retryTimes(RETRY_TIMES, { logErrorsBeforeRetry: true })
        jest.setTimeout(JEST_TIMEOUT_MS)
    },
    async postVisit(page, context) {
        const browserContext = page.context()
        const storyContext = await getStoryContext(page, context)
        const { snapshotBrowsers = ['chromium'] } = storyContext.parameters?.testOptions ?? {}

        browserContext.setDefaultTimeout(PLAYWRIGHT_TIMEOUT_MS)
        const currentBrowser = browserContext.browser()!.browserType().name() as SupportedBrowserName
        if (snapshotBrowsers.includes(currentBrowser)) {
            await expectStoryToMatchSnapshot(page, context, storyContext, currentBrowser)
        }
    },
    tags: {
        skip: ['test-skip'], // NOTE: This is overridden by the CI action storybook-chromatic.yml to include browser specific skipping
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
        theme: SnapshotTheme,
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

    await waitForPageReady(page)
    await page.evaluate(() => {
        // Stop all animations for consistent snapshots
        document.body.classList.add('storybook-test-runner')
    })
    if (waitForLoadersToDisappear) {
        // The timeout is reduced so that we never allow toasts – they usually signify something wrong
        await page.waitForSelector(LOADER_SELECTORS.join(','), { state: 'detached', timeout: 1000 })
    }
    if (waitForSelector) {
        await page.waitForSelector(waitForSelector)
    }

    await page.waitForTimeout(400) // Wait for effects to finish

    // Wait for all images to load
    await page.waitForFunction(() =>
        Array.from(document.querySelectorAll('img')).every((i: HTMLImageElement) => i.complete)
    )

    // snapshot light theme
    await page.evaluate(() => {
        document.body.setAttribute('theme', 'light')
    })

    await check(page, context, browser, 'light', storyContext.parameters?.testOptions?.snapshotTargetSelector)

    // snapshot dark theme
    await page.evaluate(() => {
        document.body.setAttribute('theme', 'dark')
    })

    await check(page, context, browser, 'dark', storyContext.parameters?.testOptions?.snapshotTargetSelector)
}

async function expectStoryToMatchFullPageSnapshot(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName,
    theme: SnapshotTheme
): Promise<void> {
    await expectLocatorToMatchStorySnapshot(page, context, browser, theme)
}

async function expectStoryToMatchSceneSnapshot(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName,
    theme: SnapshotTheme
): Promise<void> {
    await page.evaluate(() => {
        // The screenshot gets clipped by overflow hidden on .Navigation3000
        document.querySelector('Navigation3000')?.setAttribute('style', 'overflow: visible;')
    })

    await expectLocatorToMatchStorySnapshot(page.locator('main'), context, browser, theme)
}

async function expectStoryToMatchComponentSnapshot(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName,
    theme: SnapshotTheme,
    targetSelector: string = '#storybook-root'
): Promise<void> {
    await page.evaluate((theme) => {
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
        // For legacy style, make the body transparent to take the screenshot without background
        document.body.style.background = theme === 'legacy' ? 'transparent' : 'var(--bg-3000)'
    }, theme)

    await expectLocatorToMatchStorySnapshot(page.locator(targetSelector), context, browser, theme, {
        omitBackground: true,
    })
}

async function expectLocatorToMatchStorySnapshot(
    locator: Locator | Page,
    context: TestContext,
    browser: SupportedBrowserName,
    theme: SnapshotTheme,
    options?: LocatorScreenshotOptions
): Promise<void> {
    const image = await locator.screenshot({ ...options })
    let customSnapshotIdentifier = context.id
    if (theme !== 'legacy') {
        customSnapshotIdentifier += `--${theme}`
    }
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
