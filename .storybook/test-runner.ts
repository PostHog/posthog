import { toMatchImageSnapshot } from 'jest-image-snapshot'
import { getStoryContext, TestRunnerConfig, TestContext } from '@storybook/test-runner'
import { Locator, Page, LocatorScreenshotOptions } from 'playwright-core'

const customSnapshotsDir = `${process.cwd()}/frontend/__snapshots__`
const updateSnapshot = expect.getState().snapshotState._updateSnapshot === 'all'

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

        if (!storyContext.parameters?.chromatic?.disableSnapshot) {
            let expectStoryToMatchSnapshot: (page: Page, context: TestContext) => Promise<void>
            if (storyContext.parameters?.layout === 'fullscreen') {
                if (storyContext.parameters.testRunner?.includeNavigation) {
                    expectStoryToMatchSnapshot = expectStoryToMatchFullPageSnapshot
                } else {
                    expectStoryToMatchSnapshot = expectStoryToMatchSceneSnapshot
                }
            } else {
                expectStoryToMatchSnapshot = expectStoryToMatchComponentSnapshot
            }

            if (updateSnapshot) {
                // You'd expect that the 'load' @storybook/test-runner waits for would already mean the story is ready,
                // and definitely that 'networkidle' would indicate all assets to be ready. But that's not the case,
                // so we need to introduce a bit of a delay
                await page.waitForTimeout(1000)
                await expectStoryToMatchSnapshot(page, context) // Don't retry when updating
            } else {
                try {
                    await expectStoryToMatchSnapshot(page, context) // Run check immediately after render
                } catch {
                    await page.waitForTimeout(1000) // Retry a moment later in case something failed to load in time
                    await expectStoryToMatchSnapshot(page, context) // Run check again
                    console.warn('Flaky test warning - this snapshot only matched after a retry')
                }
            }
        }
    },
} as TestRunnerConfig
