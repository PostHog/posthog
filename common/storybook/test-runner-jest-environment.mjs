// Storybook 10's test-runner ships its own Playwright environment (which already
// calls setupPage) and no longer depends on jest-playwright-preset. Extend that
// environment and add our failure handling on top.
import { setupPage } from '@storybook/test-runner'
import BaseEnvironment from '@storybook/test-runner/playwright/custom-environment.js'

const PAGE_LIVENESS_TIMEOUT_MS = 5000
const PAGE_REPLACEMENT_TIMEOUT_MS = 60000

function withTimeout(promise, timeoutMs, message) {
    let timeoutId
    const timeout = new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(message)), timeoutMs)
    })
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timeoutId))
}

class CustomEnvironment extends BaseEnvironment {
    async handleTestEvent(event) {
        if (event.name === 'test_done' && event.test.errors.length > 0) {
            if (await this.pageResponds()) {
                await this.takeFailureScreenshot(event.test)
            } else {
                await this.replaceUnresponsivePage(event.test)
            }
        }
        await super.handleTestEvent(event)
    }

    async pageResponds() {
        return withTimeout(
            this.global.page.evaluate(() => true),
            PAGE_LIVENESS_TIMEOUT_MS,
            'page did not respond'
        )
            .then(() => true)
            .catch(() => false)
    }

    async takeFailureScreenshot(test) {
        // These become Actions artifacts
        const parentName = test.parent.parent.name.replace(/\W/g, '-').toLowerCase()
        const specName = test.parent.name.replace(/\W/g, '-').toLowerCase()
        await this.global.page
            .locator('body, main')
            .last()
            .screenshot({
                path: `frontend/__snapshots__/__failures__/${parentName}--${specName}.png`,
                timeout: 5000,
            })
            .catch(() => undefined)
    }

    // One page serves every story in a file. When its main thread stops answering, every later
    // page.evaluate waits forever, so each remaining story and retry in the file runs into the jest
    // timeout. A new browser context gets a new renderer process, which lets the retry and the
    // remaining stories run.
    async replaceUnresponsivePage(test) {
        // eslint-disable-next-line no-console
        console.warn(`[test-runner] Page stopped responding during "${test.name}". Replacing it.`)
        try {
            await withTimeout(
                (async () => {
                    await this.global.jestPlaywright.resetContext()
                    await setupPage(this.global.page, this.global.context)
                })(),
                PAGE_REPLACEMENT_TIMEOUT_MS,
                `page replacement did not finish within ${PAGE_REPLACEMENT_TIMEOUT_MS}ms`
            )
        } catch (error) {
            // eslint-disable-next-line no-console
            console.warn(`[test-runner] Could not replace the page: ${error.message}`)
        }
    }
}

export default CustomEnvironment
