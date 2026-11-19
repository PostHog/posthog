// Storybook 10's test-runner ships its own Playwright environment (which already
// calls setupPage) and no longer depends on jest-playwright-preset. Extend that
// environment and add our failure handling on top.
import { setupPage } from '@storybook/test-runner'
import BaseEnvironment from '@storybook/test-runner/playwright/custom-environment.js'

const PAGE_LIVENESS_TIMEOUT_MS = 5000
// Longer than the navigation retries in `prepare` (test-runner.ts) can take, so a slow but healthy
// reload still finishes.
const PAGE_REPLACEMENT_TIMEOUT_MS = 180000
const CANCELLED_REPLACEMENT_SETTLE_MS = 10000

function withTimeout(promise, timeoutMs, message) {
    let timeoutId
    const timeout = new Promise((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(message)), timeoutMs)
    })
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timeoutId))
}

const CPU_SAMPLE_MS = 1000

class CustomEnvironment extends BaseEnvironment {
    async setup() {
        await super.setup()
        await this.attachPageSession()
    }

    // A frozen renderer accepts no new DevTools session, so the session that diagnoses a freeze must
    // exist before it. WebKit and Firefox have no DevTools protocol, so they skip the diagnosis.
    async attachPageSession() {
        this.pageSession = await this.global.context.newCDPSession(this.global.page).catch(() => null)
    }

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

    // A script that never yields keeps the renderer near 100% CPU and stops when the session terminates
    // it. A renderer that waits on another process, such as the GPU process, uses no CPU and stays frozen.
    async diagnoseFreeze() {
        if (!this.pageSession) {
            return 'No diagnosis in this browser.'
        }
        const cpu = await withTimeout(this.sampleRendererCpu(), PAGE_LIVENESS_TIMEOUT_MS, 'CPU sample timed out').catch(
            (error) => error.message
        )
        await this.pageSession.send('Runtime.terminateExecution').catch(() => undefined)
        const outcome = (await this.pageResponds())
            ? 'The page recovered when its script was stopped, so a script was running without end.'
            : 'The page stayed frozen after its script was stopped, so no script loop holds it.'
        return `Renderer CPU: ${cpu}. ${outcome}`
    }

    async sampleRendererCpu() {
        const browserSession = await this.global.browser.newBrowserCDPSession()
        const read = async () => {
            const { processInfo } = await browserSession.send('SystemInfo.getProcessInfo')
            return new Map(
                processInfo.filter(({ type }) => type === 'renderer').map(({ id, cpuTime }) => [id, cpuTime])
            )
        }
        try {
            const before = await read()
            await new Promise((resolve) => setTimeout(resolve, CPU_SAMPLE_MS))
            const after = await read()
            return [...after]
                .map(([id, cpuTime]) => `${Math.round(((cpuTime - (before.get(id) ?? 0)) * 100000) / CPU_SAMPLE_MS)}%`)
                .join(', ')
        } finally {
            await browserSession.detach().catch(() => undefined)
        }
    }

    // One page serves every story in a file. When its main thread stops answering, every later
    // page.evaluate waits forever, so each remaining story and retry in the file runs into the jest
    // timeout. A new browser context gets a new renderer process, which lets the retry and the
    // remaining stories run.
    async replaceUnresponsivePage(test) {
        // eslint-disable-next-line no-console
        console.warn(
            `[test-runner] Page stopped responding during "${test.name}". ${await this.diagnoseFreeze()} Replacing it.`
        )
        const replacement = (async () => {
            await this.global.jestPlaywright.resetContext()
            await setupPage(this.global.page, this.global.context)
            await this.attachPageSession()
        })()
        try {
            await withTimeout(
                replacement,
                PAGE_REPLACEMENT_TIMEOUT_MS,
                `page replacement did not finish within ${PAGE_REPLACEMENT_TIMEOUT_MS}ms`
            )
        } catch (error) {
            // eslint-disable-next-line no-console
            console.warn(`[test-runner] Could not replace the page: ${error.message}`)
            // Closing the context stops the navigation and script injection that are still running, so
            // the next story fails at once on a closed page instead of running on a half-prepared one.
            await this.global.context?.close().catch(() => undefined)
            await withTimeout(replacement, CANCELLED_REPLACEMENT_SETTLE_MS, 'cancelled replacement').catch(
                () => undefined
            )
        }
    }
}

export default CustomEnvironment
