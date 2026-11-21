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

function storyName(test) {
    return `${test.parent.parent.name} › ${test.parent.name} › ${test.name}`
}

// jest indents console output, and GitHub only reads a workflow command that starts its own line, so
// the annotation goes straight to stdout. It shows in the run summary and in the check run annotations.
function writeWarningAnnotation(title, message) {
    if (!process.env.GITHUB_ACTIONS) {
        return
    }
    const escape = (text) => text.replace(/%/g, '%25').replace(/\r/g, '%0D').replace(/\n/g, '%0A')
    process.stdout.write(`\n::warning title=${title}::${escape(message)}\n`)
}

const CPU_SAMPLE_MS = 1000
const STACK_CAPTURE_TIMEOUT_MS = 3000
const STACK_FRAME_LIMIT = 8

class CustomEnvironment extends BaseEnvironment {
    async setup() {
        await super.setup()
        await this.attachPageSession()
    }

    // A frozen renderer accepts no new DevTools session, and its debugger cannot be enabled, so both must
    // exist before the freeze for the diagnosis to pause the page and read its stack. WebKit and Firefox
    // have no DevTools protocol, so they skip the diagnosis.
    async attachPageSession() {
        try {
            this.pageSession = await this.global.context.newCDPSession(this.global.page)
            // Paused call frames carry only a script id, so keep each script's file name to print the stack.
            this.scriptFiles = new Map()
            this.pageSession.on('Debugger.scriptParsed', ({ scriptId, url }) => {
                this.scriptFiles.set(scriptId, url ? url.split('?')[0].split('/').pop() : 'inline')
            })
            await this.pageSession.send('Debugger.enable')
            // With breakpoints active, a `debugger` statement in story or dependency code pauses the page and
            // nothing resumes it. Debugger.pause still pauses the page when breakpoints are inactive.
            await this.pageSession.send('Debugger.setBreakpointsActive', { active: false })
        } catch {
            this.pageSession = null
        }
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

    // A script that never yields keeps the renderer near 100% CPU, has a JavaScript stack, and stops when
    // the session terminates it. A renderer that waits on another process, such as the GPU process, uses
    // no CPU and stays frozen.
    async diagnoseFreeze() {
        if (!this.pageSession) {
            return 'No diagnosis in this browser.'
        }
        const cpu = await withTimeout(this.sampleProcessCpu(), PAGE_LIVENESS_TIMEOUT_MS, 'CPU sample timed out').catch(
            (error) => error.message
        )
        const stack = await this.captureStack()
        // Chromium serves these commands from the page's main thread or through a V8 interrupt, so a page
        // blocked outside script never answers them.
        // Disabling the debugger also resumes the paused page, which terminateExecution needs to take effect.
        await withTimeout(
            this.pageSession.send('Debugger.disable'),
            PAGE_LIVENESS_TIMEOUT_MS,
            'Debugger.disable timed out'
        ).catch(() => undefined)
        await withTimeout(
            this.pageSession.send('Runtime.terminateExecution'),
            PAGE_LIVENESS_TIMEOUT_MS,
            'terminateExecution timed out'
        ).catch(() => undefined)
        const outcome = (await this.pageResponds())
            ? 'The page recovered when its script was stopped, so a script was running without end.'
            : 'The page stayed frozen after its script was stopped, so no script loop holds it.'
        return `CPU: ${cpu}. Stack: ${stack}. ${outcome}`
    }

    async captureStack() {
        const paused = new Promise((resolve) => this.pageSession.once('Debugger.paused', resolve))
        try {
            await withTimeout(this.pageSession.send('Debugger.pause'), STACK_CAPTURE_TIMEOUT_MS, 'pause timed out')
            const { callFrames } = await withTimeout(paused, STACK_CAPTURE_TIMEOUT_MS, 'no paused event')
            if (!callFrames.length) {
                return 'none'
            }
            return callFrames
                .slice(0, STACK_FRAME_LIMIT)
                .map(({ functionName, location }) => {
                    const file = this.scriptFiles.get(location.scriptId) ?? 'unknown'
                    return `${functionName || '(anonymous)'} ${file}:${location.lineNumber + 1}:${location.columnNumber + 1}`
                })
                .join(' < ')
        } catch (error) {
            return `unavailable (${error.message})`
        }
    }

    async sampleProcessCpu() {
        const browserSession = await this.global.browser.newBrowserCDPSession()
        const read = async () => (await browserSession.send('SystemInfo.getProcessInfo')).processInfo
        try {
            const before = new Map((await read()).map(({ id, cpuTime }) => [id, cpuTime]))
            await new Promise((resolve) => setTimeout(resolve, CPU_SAMPLE_MS))
            return (await read())
                .filter(({ type }) => ['renderer', 'GPU', 'browser'].includes(type))
                .map(({ type, id, cpuTime }) => {
                    const percent = Math.round(((cpuTime - (before.get(id) ?? 0)) * 100000) / CPU_SAMPLE_MS)
                    return `${type} ${percent}%`
                })
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
        const message = `Page stopped responding during "${storyName(test)}". ${await this.diagnoseFreeze()} Replacing it.`
        // eslint-disable-next-line no-console
        console.warn(`[test-runner] ${message}`)
        writeWarningAnnotation('Storybook page froze', message)
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
