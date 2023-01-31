import { toMatchImageSnapshot } from 'jest-image-snapshot'
import { OptionsParameter } from '@storybook/addons'
import { getStoryContext, TestRunnerConfig, TestContext } from '@storybook/test-runner'
import type { Locator, Page, LocatorScreenshotOptions } from 'playwright-core'
import type { Mocks } from '~/mocks/utils'

// Extend Storybook interface `Parameters` with Chromatic parameters
declare module '@storybook/react' {
    interface Parameters {
        options?: OptionsParameter
        layout?: 'padded' | 'fullscreen' | 'centered'
        testOptions?: {
            /** Whether the test should be a no-op (doesn't jest.skip as @storybook/test-runner doesn't allow that). **/
            skip?: boolean
            /**
             * Whether navigation (sidebar + topbar) should be excluded from the snapshot.
             * Warning: Fails if enabled for stories in which navigation is not present.
             */
            excludeNavigationFromSnapshot?: boolean
        }
        mockDate?: string | number | Date
        msw?: {
            mocks?: Mocks
        }
        [name: string]: any
    }
}

const RETRY_TIMES = 3

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
    const image = await locator.screenshot({ timeout: 3000, ...options })
    expect(image).toMatchImageSnapshot({
        customSnapshotsDir,
        customSnapshotIdentifier: context.id,
    })
}

module.exports = {
    setup() {
        expect.extend({ toMatchImageSnapshot })
        jest.retryTimes(RETRY_TIMES, { logErrorsBeforeRetry: true })
    },
    async postRender(page, context) {
        const storyContext = await getStoryContext(page, context)

        await page.evaluate(() => {
            // Stop all animations for consistent snapshots
            document.body.classList.add('dangerously-stop-all-animations')
        })

        if (!storyContext.parameters?.testOptions?.skip) {
            let expectStoryToMatchSnapshot: (page: Page, context: TestContext) => Promise<void>
            if (storyContext.parameters?.layout === 'fullscreen') {
                if (storyContext.parameters.testOptions?.excludeNavigationFromSnapshot) {
                    expectStoryToMatchSnapshot = expectStoryToMatchSceneSnapshot
                } else {
                    expectStoryToMatchSnapshot = expectStoryToMatchFullPageSnapshot
                }
            } else {
                expectStoryToMatchSnapshot = expectStoryToMatchComponentSnapshot
            }

            // You'd expect that the 'load' state which @storybook/test-runner waits for would already mean
            // the story is ready, and definitely that 'networkidle' would indicate all assets to be ready.
            // But that's not the case, so we need to introduce a bit of a delay.
            // The delay is extended when updating snapshots, so that we're 100% sure they represent the final state.
            const delayMultiplier: number = updateSnapshot ? RETRY_TIMES : 1
            await page.waitForTimeout(250 * delayMultiplier)
            await expectStoryToMatchSnapshot(page, context) // Don't retry when updating
        }
    },
} as TestRunnerConfig
