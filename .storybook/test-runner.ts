import { toMatchImageSnapshot } from 'jest-image-snapshot'
import { getStoryContext, TestRunnerConfig, TestContext } from '@storybook/test-runner'
import { Locator, Page, LocatorScreenshotOptions } from 'playwright-core'

const customSnapshotsDir = `${process.cwd()}/frontend/__snapshots__`

async function expectStoryToMatchFullPageSnapshot(page: Page, context: TestContext): Promise<void> {
    await expectLocatorToMatchStorySnapshot(page, context)
}

async function expectStoryToMatchSceneSnapshot(page: Page, context: TestContext): Promise<void> {
    await expectLocatorToMatchStorySnapshot(page.locator('.main-app-content'), context)
}

async function expectStoryToMatchComponentSnapshot(page: Page, context: TestContext): Promise<void> {
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

    await expectLocatorToMatchStorySnapshot(page.locator('#root'), context, { omitBackground: true })
}

async function expectLocatorToMatchStorySnapshot(
    locator: Locator | Page,
    context: TestContext,
    options?: LocatorScreenshotOptions
): Promise<void> {
    const image = await locator.screenshot(options)
    expect(image).toMatchImageSnapshot({
        customSnapshotsDir,
        customSnapshotIdentifier: context.id,
    })
}

module.exports = {
    setup() {
        expect.extend({ toMatchImageSnapshot })
    },
    async postRender(page, context) {
        const storyContext = await getStoryContext(page, context)

        await page.evaluate(() => {
            // Stop all animations for consistent snapshots
            document.body.classList.add('dangerously-stop-all-animations')
        })

        // Wait for the network to be idle for up to 500 ms, to allow assets like images to load. This is suboptimal,
        // because `networkidle` is not resolved reliably here, so we might wait for the full timeout - but it works.
        await Promise.race([page.waitForLoadState('networkidle'), page.waitForTimeout(500)])

        if (!storyContext.parameters?.chromatic?.disableSnapshot) {
            if (storyContext.parameters?.layout === 'fullscreen') {
                if (storyContext.parameters.testRunner?.includeNavigation) {
                    await expectStoryToMatchFullPageSnapshot(page, context)
                } else {
                    await expectStoryToMatchSceneSnapshot(page, context)
                }
            } else {
                await expectStoryToMatchComponentSnapshot(page, context)
            }
        }
    },
} as TestRunnerConfig
