// Run against the LiveRuntime Storybook story on each branch to compare main-thread work during Doom.
// From the repository root: node frontend/bin/bench-terminal.mjs http://localhost:6006
import { chromium } from 'playwright'

const story = new URL(
    '/iframe.html?id=scenes-app-terminal--live-runtime&viewMode=story',
    process.argv[2] || 'http://localhost:6006'
)
const browser = await chromium.launch()
try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
    const workerUrls = []
    page.on('worker', (worker) => workerUrls.push(worker.url()))
    await page.goto(story.href, { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await page.waitForFunction(() => !!window.posthogTerminal, null, { timeout: 120_000 })
    await page.waitForFunction(() => window.posthogTerminal.read().endsWith('\x1b]133;B\x07'))
    await page.evaluate(() => window.posthogTerminal.write('doom\n'))
    await page.waitForFunction(() => window.posthogTerminal.read().includes('Mouse input ready'), null, {
        timeout: 120_000,
    })
    await page.locator('[data-attr="terminal-display-screen"]').click()
    for (let i = 0; i < 4; i++) {
        await page.keyboard.press('Enter')
        // Doom polls the PS/2 keyboard on guest ticks.
        await page.waitForTimeout(500)
    }
    await page.keyboard.down('KeyW')
    await page.waitForTimeout(1000)
    await page.keyboard.up('KeyW')
    const cdp = await page.context().newCDPSession(page)
    await cdp.send('Performance.enable')
    const before = await cdp.send('Performance.getMetrics')
    await page.evaluate(() => {
        window.terminalBenchmark = { gaps: [], tasks: [], timer: null, observer: null }
        const state = window.terminalBenchmark
        let last = performance.now()
        state.timer = setInterval(() => {
            const now = performance.now()
            state.gaps.push(now - last)
            last = now
        }, 16)
        state.observer = new PerformanceObserver((list) =>
            state.tasks.push(...list.getEntries().map((entry) => entry.duration))
        )
        state.observer.observe({ type: 'longtask', buffered: false })
    })
    const start = performance.now()
    // Fixed sampling window, not a timing assertion: this is a benchmark, not a CI test.
    await page.waitForTimeout(10_000)
    const elapsed = performance.now() - start
    const after = await cdp.send('Performance.getMetrics')
    const responsiveness = await page.evaluate(() => {
        const { gaps, tasks, timer, observer } = window.terminalBenchmark
        clearInterval(timer)
        observer.disconnect()
        delete window.terminalBenchmark
        gaps.sort((a, b) => a - b)
        return {
            heartbeatMaxMs: Math.max(...gaps),
            heartbeatP95Ms: gaps[Math.floor(gaps.length * 0.95)],
            longTasks: tasks.length,
            longTaskMs: tasks.reduce((sum, duration) => sum + duration, 0),
        }
    })
    const delta = (name) =>
        after.metrics.find((metric) => metric.name === name).value -
        before.metrics.find((metric) => metric.name === name).value
    console.info(
        JSON.stringify(
            {
                elapsedMs: elapsed,
                mainThreadTaskMs: delta('TaskDuration') * 1000,
                mainThreadScriptMs: delta('ScriptDuration') * 1000,
                ...responsiveness,
                workerUrls,
            },
            null,
            2
        )
    )
    await page.screenshot({ path: '/tmp/terminal-doom-benchmark.png' })
    await page.locator('[data-attr="terminal-display-close"]').click()
    await page.locator('[data-attr="terminal-stop"]').click()
} finally {
    await browser.close()
}
