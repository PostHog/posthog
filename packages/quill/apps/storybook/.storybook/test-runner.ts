import type { TestRunnerConfig } from '@storybook/test-runner'
import { getStoryContext } from '@storybook/test-runner'
import { toMatchImageSnapshot } from 'jest-image-snapshot'
import path from 'path'

type SnapshotTheme = 'light' | 'dark'
// Use inline types to avoid playwright-core version conflicts in the monorepo
type Page = any
type TestContext = any

const customSnapshotsDir = path.resolve(__dirname, '../__snapshots__')

module.exports = {
    setup() {
        expect.extend({ toMatchImageSnapshot })
        jest.retryTimes(2, { logErrorsBeforeRetry: true })
    },

    async preVisit(page) {
        await page.setViewportSize({ width: 448, height: 720 })
    },

    async postVisit(page, context) {
        const storyContext = await getStoryContext(page, context)
        const { skipDarkMode = false } = storyContext.parameters?.testOptions ?? {}

        await waitForPageReady(page)

        // Add class for snapshot-safe styling (animations disabled via CSS)
        await page.evaluate(() => {
            document.body.classList.add('storybook-test-runner')
        })

        // Wait for content to stabilize
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
                // proceed if content keeps changing
            })

        // Snapshot light theme
        await takeSnapshot(page, context, 'light')

        // Snapshot dark theme
        if (!skipDarkMode) {
            await takeSnapshot(page, context, 'dark')
        }
    },
} as TestRunnerConfig

async function takeSnapshot(page: Page, context: TestContext, theme: SnapshotTheme): Promise<void> {
    // Set theme via class on html element (matches quill's ThemeProvider)
    await page.evaluate((t: string) => {
        document.documentElement.classList.remove('light', 'dark')
        document.documentElement.classList.add(t)
    }, theme)

    // Wait for theme to settle
    await page.waitForTimeout(100)

    // Calculate bounding box that includes both #storybook-root and any floating UI portals
    const clip = await page.evaluate(() => {
        const rootEl = document.getElementById('storybook-root')
        if (!rootEl) {
            return null
        }

        const rootRect = rootEl.getBoundingClientRect()
        let top = rootRect.top
        let left = rootRect.left
        let bottom = rootRect.bottom
        let right = rootRect.right

        // Find all floating UI portals (Base UI renders these outside #storybook-root)
        const floatingSelectors = [
            '[data-floating-ui-portal]',
            '[role="listbox"]',
            '[role="menu"]',
            '[role="dialog"]',
            '[role="tooltip"]',
            '[data-popup]',
        ]

        document.querySelectorAll(floatingSelectors.join(',')).forEach((el) => {
            const rect = el.getBoundingClientRect()
            if (rect.width === 0 && rect.height === 0) {
                return
            }
            top = Math.min(top, rect.top)
            left = Math.min(left, rect.left)
            bottom = Math.max(bottom, rect.bottom)
            right = Math.max(right, rect.right)
        })

        const pad = 16
        const x = Math.max(0, left - pad)
        const y = Math.max(0, top - pad)

        return {
            x,
            y,
            width: right + pad - x,
            height: bottom + pad - y,
        }
    })

    // Screenshot the combined area (root + floating elements)
    const image = clip
        ? await page.screenshot({ omitBackground: true, clip })
        : await page.locator('#storybook-root').screenshot({ omitBackground: true })

    expect(image).toMatchImageSnapshot({
        customSnapshotsDir,
        customSnapshotIdentifier: `${context.id}--${theme}`,
        comparisonMethod: 'ssim',
        failureThreshold: 0.01,
        failureThresholdType: 'percent',
    })
}

async function waitForPageReady(page: Page): Promise<void> {
    await page.waitForLoadState('domcontentloaded')
    await page.waitForLoadState('load')
    await page.evaluate(() => document.fonts.ready)
}
