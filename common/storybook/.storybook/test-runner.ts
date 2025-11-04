import type { Locator, LocatorScreenshotOptions, Page } from '@playwright/test'
import { StoryContext } from '@storybook/csf'
import { TestContext, TestRunnerConfig, getStoryContext } from '@storybook/test-runner'
import { toMatchImageSnapshot } from 'jest-image-snapshot'
import path from 'path'

import type { Mocks } from '~/mocks/utils'

const DEFAULT_VIEWPORT = { width: 1280, height: 720 }

// 'firefox' is technically supported too, but as of June 2023 it has memory usage issues that make is unusable
type SupportedBrowserName = 'chromium' | 'webkit'
type SnapshotTheme = 'light' | 'dark'

// Extend Storybook interface `Parameters` with Chromatic parameters
declare module '@storybook/types' {
    interface Parameters {
        options?: any
        /** @default 'padded' */
        layout?: 'padded' | 'fullscreen' | 'centered'
        testOptions?: {
            /**
             * Whether we should wait for all loading indicators to disappear before taking a snapshot.
             * @default true
             */
            waitForLoadersToDisappear?: boolean
            /** If set, we'll wait for the given selector (or all selectors, if multiple) to be satisfied. */
            waitForSelector?: string | string[]
            /**
             * By default we wait for images to have width as an indication the page is ready for screenshot testing
             * Some stories have broken images on purpose to test what the UI does
             * in those cases set `allowImagesWithoutWidth` to `true`
             */
            allowImagesWithoutWidth?: boolean
            /**
             * Whether navigation should be included in the snapshot. Only applies to `layout: 'fullscreen'` stories.
             * @default false
             */
            includeNavigationInSnapshot?: boolean
            /**
             * The test will always run for all the browers, but snapshots are only taken in Chromium by default.
             * Override this to take snapshots in other browsers too.
             *
             * @default ['chromium']
             */
            snapshotBrowsers?: SupportedBrowserName[]
            /** If taking a component snapshot, you can narrow it down by specifying the selector. */
            snapshotTargetSelector?: string
            /** specify an alternative viewport size */
            viewport?: { width: number; height: number }
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

const RETRY_TIMES = 2
const LOADER_SELECTORS = [
    '.Spinner',
    '.LemonSkeleton',
    '.LemonTableLoader',
    '.Toastify__toast',
    '[aria-busy="true"]',
    '.SessionRecordingPlayer--buffering',
    '.Lettermark--unknown',
    '[data-attr="loading-bar"]',
]

const customSnapshotsDir = path.resolve(__dirname, '../../../frontend/__snapshots__')
// eslint-disable-next-line no-console
console.log('[test-runner] Storybook snapshots will be saved to', customSnapshotsDir)

const JEST_TIMEOUT_MS = 15000
const PLAYWRIGHT_TIMEOUT_MS = 10000 // Must be shorter than JEST_TIMEOUT_MS

const ATTEMPT_COUNT_PER_ID: Record<string, number> = {}

module.exports = {
    setup() {
        expect.extend({ toMatchImageSnapshot })
        jest.retryTimes(RETRY_TIMES, { logErrorsBeforeRetry: true })
        jest.setTimeout(JEST_TIMEOUT_MS)
    },

    async preVisit(page, context) {
        const storyContext = await getStoryContext(page, context)
        const viewport = storyContext.parameters?.testOptions?.viewport || DEFAULT_VIEWPORT
        await page.setViewportSize(viewport)
    },

    async postVisit(page, context) {
        ATTEMPT_COUNT_PER_ID[context.id] = (ATTEMPT_COUNT_PER_ID[context.id] || 0) + 1
        const storyContext = await getStoryContext(page, context)
        const viewport = storyContext.parameters?.testOptions?.viewport || DEFAULT_VIEWPORT

        await page.evaluate(
            // eslint-disable-next-line no-console
            ([retry, id]) => console.log(`[${id}] Attempt ${retry}`),
            [ATTEMPT_COUNT_PER_ID[context.id], context.id]
        )

        if (ATTEMPT_COUNT_PER_ID[context.id] > 1) {
            // When retrying, resize the viewport and then resize again to default,
            // just in case the retry is due to a useResizeObserver fail
            await page.setViewportSize({ width: 1920, height: 1080 })
            await page.setViewportSize(viewport)
        }

        const browserContext = page.context()
        const { snapshotBrowsers = ['chromium'] } = storyContext.parameters?.testOptions ?? {}

        browserContext.setDefaultTimeout(PLAYWRIGHT_TIMEOUT_MS)
        const currentBrowser = browserContext.browser()!.browserType().name() as SupportedBrowserName
        if (snapshotBrowsers.includes(currentBrowser)) {
            await expectStoryToMatchSnapshot(page, context, storyContext, currentBrowser)
        }
    },
    tags: {
        skip: ['test-skip'], // NOTE: This is overridden by the CI action ci-storybook.yml to include browser specific skipping
    },
} as TestRunnerConfig

async function expectStoryToMatchSnapshot(
    page: Page,
    context: TestContext,
    storyContext: StoryContext,
    browser: SupportedBrowserName
): Promise<void> {
    await waitForPageReady(page)

    // set up iframe load tracking early, before they start loading
    await page.evaluate(() => {
        // use MutationObserver to catch iframes as they're added to the DOM
        const trackIframeLoad = (iframe: HTMLIFrameElement): void => {
            if (!iframe.hasAttribute('data-load-tracked')) {
                iframe.setAttribute('data-load-tracked', 'loading')
                iframe.addEventListener(
                    'load',
                    () => {
                        iframe.setAttribute('data-load-tracked', 'loaded')
                    },
                    { once: true }
                )
            }
        }

        // track existing iframes
        document.querySelectorAll('iframe').forEach(trackIframeLoad)

        // track future iframes
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node instanceof HTMLIFrameElement) {
                        trackIframeLoad(node)
                    }
                    if (node instanceof Element) {
                        node.querySelectorAll('iframe').forEach(trackIframeLoad)
                    }
                })
            })
        })
        observer.observe(document.body, { childList: true, subtree: true })
        ;(window as Window & { __iframeObserver?: MutationObserver }).__iframeObserver = observer
    })

    await page.evaluate((layout: string) => {
        // Stop all animations for consistent snapshots, and adjust other styles
        document.body.classList.add('storybook-test-runner')
        document.body.classList.add(`storybook-test-runner--${layout}`)
    }, storyContext.parameters?.layout || 'padded')

    const { waitForLoadersToDisappear = true, waitForSelector } = storyContext.parameters?.testOptions ?? {}

    if (waitForLoadersToDisappear) {
        // The timeout is reduced so that we never allow toasts – they usually signify something wrong
        await page.waitForSelector(LOADER_SELECTORS.join(','), { state: 'detached', timeout: 3000 })
    }

    if (typeof waitForSelector === 'string') {
        await page.waitForSelector(waitForSelector)
    } else if (Array.isArray(waitForSelector)) {
        await Promise.all(waitForSelector.map((selector) => page.waitForSelector(selector)))
    }

    // Snapshot both light and dark themes
    await takeSnapshotWithTheme(page, context, browser, 'light', storyContext)
    await takeSnapshotWithTheme(page, context, browser, 'dark', storyContext)
}

async function takeSnapshotWithTheme(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName,
    theme: SnapshotTheme,
    storyContext: StoryContext
): Promise<void> {
    const { allowImagesWithoutWidth = false } = storyContext.parameters?.testOptions ?? {}

    // Set the right theme
    await page.evaluate((theme: SnapshotTheme) => document.body.setAttribute('theme', theme), theme)

    // Wait until we're sure we've finished loading everything
    await waitForPageReady(page)
    // check if all images have width, unless purposefully skipped
    if (!allowImagesWithoutWidth) {
        await page.waitForFunction(() => {
            const allImages = Array.from(document.images)
            const areAllImagesLoaded = allImages.every(
                // ProseMirror-separator isn't an actual image of any sort, so we ignore those
                (i: HTMLImageElement) => !!i.naturalWidth || i.classList.contains('ProseMirror-separator')
            )
            if (areAllImagesLoaded) {
                // Hide gifs to prevent their animations causing flakiness
                for (const image of allImages) {
                    if (image.src.endsWith('.gif')) {
                        image.style.visibility = 'hidden'
                        image.style.background = 'red'
                    }
                }
            }
            return areAllImagesLoaded
        })
    }

    // wait for iframes to load their content
    const iframeCount = await page.locator('iframe').count()
    if (iframeCount > 0) {
        await page
            .waitForFunction(
                () => {
                    const iframes = Array.from(document.querySelectorAll('iframe'))
                    return iframes.every((iframe) => iframe.getAttribute('data-load-tracked') === 'loaded')
                },
                { timeout: 8000 }
            )
            .catch(() => {
                // if timeout, that's okay - some iframes might not fire load events
            })
        // give iframe content a moment to render after load event
        await page.waitForTimeout(1000)
    }

    // wait for content to stabilize - detects when DOM stops changing
    await page
        .waitForFunction(
            () => {
                return new Promise<boolean>((resolve) => {
                    let lastHeight = document.body.scrollHeight
                    let lastWidth = document.body.scrollWidth
                    let stableCount = 0

                    const checkStability = (): void => {
                        const currentHeight = document.body.scrollHeight
                        const currentWidth = document.body.scrollWidth

                        if (currentHeight === lastHeight && currentWidth === lastWidth) {
                            stableCount++
                            if (stableCount >= 3) {
                                resolve(true)
                                return
                            }
                        } else {
                            stableCount = 0
                            lastHeight = currentHeight
                            lastWidth = currentWidth
                        }

                        setTimeout(checkStability, 100)
                    }

                    checkStability()
                })
            },
            { timeout: 3000 }
        )
        .catch(() => {
            // if content keeps changing, that's okay - we'll proceed anyway
        })

    // final wait for any remaining renders
    await page.waitForTimeout(1000)

    // Do take the snapshot
    await doTakeSnapshotWithTheme(page, context, browser, theme, storyContext)
}

async function doTakeSnapshotWithTheme(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName,
    theme: SnapshotTheme,
    storyContext: StoryContext
): Promise<void> {
    const { includeNavigationInSnapshot = false, snapshotTargetSelector } = storyContext.parameters?.testOptions ?? {}

    // Figure out what's the right check function depending on the parameters
    let check: (
        page: Page,
        context: TestContext,
        browser: SupportedBrowserName,
        theme: SnapshotTheme,
        targetSelector?: string
    ) => Promise<void>
    if (storyContext.parameters?.layout === 'fullscreen') {
        if (includeNavigationInSnapshot) {
            check = expectStoryToMatchViewportSnapshot
        } else {
            check = expectStoryToMatchSceneSnapshot
        }
    } else {
        check = expectStoryToMatchComponentSnapshot
    }

    await check(page, context, browser, theme, snapshotTargetSelector)
}

async function expectStoryToMatchViewportSnapshot(
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
    // If the `main` element isn't present, let's use `body` - this is needed in logged-out screens.
    // We use .last(), because the order of selector matches is based on the order of elements in the DOM,
    // and not the order of the selectors in the query.
    await expectLocatorToMatchStorySnapshot(page.locator('body, main').last(), context, browser, theme)
}

async function expectStoryToMatchComponentSnapshot(
    page: Page,
    context: TestContext,
    browser: SupportedBrowserName,
    theme: SnapshotTheme,
    targetSelector: string = '#storybook-root'
): Promise<void> {
    await page.evaluate(() => {
        const rootEl = document.getElementById('storybook-root')
        if (!rootEl) {
            throw new Error('Could not find root element')
        }

        // If needed, expand the root element so that all popovers are visible in the screenshot
        document.querySelectorAll('.Popover, .Tooltip').forEach((popover) => {
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
    })

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
    let customSnapshotIdentifier = `${context.id}--${theme}`
    if (browser !== 'chromium') {
        customSnapshotIdentifier += `--${browser}`
    }

    expect(image).toMatchImageSnapshot({
        customSnapshotsDir,
        customSnapshotIdentifier,
        // Compare structural similarity instead of raw pixels - reducing false positives
        // See https://github.com/americanexpress/jest-image-snapshot#recommendations-when-using-ssim-comparison
        comparisonMethod: 'ssim',
        // 0.01 is a 1% difference
        failureThreshold: 0.01,
        failureThresholdType: 'percent',
    })
}

/**
 * Just like the `waitForPageReady` helper offered by Playwright - except we only wait for `networkidle` in CI,
 * as it doesn't work with local Storybook (the live reload feature keeps up a long-running request, so we aren't idle).
 */
async function waitForPageReady(page: Page): Promise<void> {
    await page.waitForLoadState('domcontentloaded')
    await page.waitForLoadState('load')

    if (process.env.CI) {
        await page.waitForLoadState('networkidle')
    }

    await page.evaluate(() => document.fonts.ready)
}
