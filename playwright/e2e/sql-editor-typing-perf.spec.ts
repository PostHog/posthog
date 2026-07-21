import { Page } from '@playwright/test'

import { SqlInsight } from '../page-models/insights/sqlInsight'
import { expect, PlaywrightWorkspaceSetupResult, test } from '../utils/workspace-test-base'

// Manual performance benchmark for typing latency in the SQL editor on a long query.
// Not part of the CI suite (perf numbers are machine-dependent and would be flaky as an
// assertion) — gated behind RUN_PERF_BENCH so it is skipped unless run explicitly:
//
//   RUN_PERF_BENCH=1 BASE_URL='http://localhost:8010' \
//     pnpm --filter=@posthog/playwright exec playwright test sql-editor-typing-perf --workers 1
//
// It types a fixed burst of keystrokes into a large query and reports main-thread long-task
// time via PerformanceObserver. To compare before/after a change, run it, `git stash` the
// change, run again, then `git stash pop` — the printed numbers are the result, not pass/fail.

// A recognizable, autocomplete-safe run of characters (no spaces/dots) typed into a comment.
const TYPE_MARKER = 'perfbenchmark'
const TYPE_CHARS = TYPE_MARKER.repeat(6) // 78 keystrokes
const TYPE_DELAY_MS = 40 // faster than the 150ms decoration debounce, so coalescing is visible

interface TypingStats {
    // Primary: main-thread jank. A requestAnimationFrame loop runs during the burst; whenever a
    // frame is delayed past 16.7ms the main thread was too busy to paint. frameBlockedMs sums
    // that overflow across the burst — it captures the many small per-keystroke parses the
    // unfixed code runs, which the coarse longtask (>50ms) API misses entirely.
    frameBlockedMs: number
    maxFrameGapMs: number
    frames: number
    // Secondary: worst single interaction latency + long-task count.
    eventMaxMs: number
    longTasks: number
}

// Build a deterministic, large, deeply-nested query: 12 chained CTEs plus a 20-level nested
// subquery tail. This is what makes the per-keystroke HogQL parse expensive.
function buildLargeQuery(): string {
    const ctes: string[] = []
    for (let i = 0; i < 12; i++) {
        const cols = Array.from({ length: 8 }, (_, j) => `col_${i}_${j} AS c${j}`).join(',\n        ')
        const aggs = Array.from({ length: 5 }, (_, j) => `sum(metric_${i}_${j}) AS a${j}`).join(',\n        ')
        const groupBy = Array.from({ length: 8 }, (_, j) => `c${j}`).join(', ')
        ctes.push(
            `cte_${i} AS (\n    SELECT\n        ${cols},\n        ${aggs}\n    FROM events\n` +
                `    WHERE col_${i}_0 > ${i * 100}\n        AND timestamp > now() - INTERVAL ${i + 1} DAY\n` +
                `    GROUP BY ${groupBy}\n)`
        )
    }

    let nested = 'SELECT base AS v, sum(x0) AS m FROM events GROUP BY v'
    for (let d = 1; d <= 20; d++) {
        nested = `SELECT v, m, max(y${d}) AS m${d} FROM (\n${nested}\n) sub_${d} WHERE m > ${d} GROUP BY v, m`
    }

    const joins = Array.from(
        { length: 11 },
        (_, i) => `    LEFT JOIN cte_${i + 1} ON cte_${i + 1}.c0 = cte_0.c${(i + 1) % 8}`
    ).join('\n')
    const finalCols = Array.from({ length: 12 }, (_, i) => `    cte_${i}.a${i % 5} AS metric_${i}`).join(',\n')

    return [
        '-- perf benchmark query',
        'WITH\n' + ctes.join(',\n'),
        `SELECT\n${finalCols}\nFROM cte_0\n${joins}\nLIMIT 100;`,
        '-- nested tail',
        nested + ';',
    ].join('\n')
}

async function startMeasuring(page: Page): Promise<void> {
    await page.evaluate(() => {
        const w = window as any
        w.__frames = []
        w.__events = []
        w.__longTasks = []
        const loop = (t: number): void => {
            w.__frames.push(t)
            w.__raf = requestAnimationFrame(loop)
        }
        w.__raf = requestAnimationFrame(loop)
        w.__evObs = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                w.__events.push(entry.duration)
            }
        })
        w.__evObs.observe({ type: 'event', durationThreshold: 16 })
        w.__ltObs = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                w.__longTasks.push(entry.duration)
            }
        })
        w.__ltObs.observe({ type: 'longtask' })
    })
}

async function stopMeasuring(page: Page): Promise<TypingStats> {
    return await page.evaluate(() => {
        const w = window as any
        cancelAnimationFrame(w.__raf)
        w.__evObs?.disconnect()
        w.__ltObs?.disconnect()

        const frames: number[] = w.__frames || []
        const FRAME_BUDGET = 1000 / 60 // 16.7ms
        let blocked = 0
        let maxGap = 0
        for (let i = 1; i < frames.length; i++) {
            const gap = frames[i] - frames[i - 1]
            blocked += Math.max(0, gap - FRAME_BUDGET)
            maxGap = Math.max(maxGap, gap)
        }
        const events: number[] = w.__events || []
        return {
            frameBlockedMs: Math.round(blocked),
            maxFrameGapMs: Math.round(maxGap),
            frames: frames.length,
            eventMaxMs: Math.round(events.length ? Math.max(...events) : 0),
            longTasks: (w.__longTasks || []).length,
        }
    })
}

async function goToSqlEditor(page: Page): Promise<void> {
    await page.goto('/sql')
    await expect(page).toHaveURL(/\/sql(?:[?#].*)?$/)
    await expect(page.getByTestId('editor-scene')).toBeVisible({ timeout: 60000 })
    await expect(page.getByTestId('hogql-query-editor')).toBeVisible()
    await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0, { timeout: 60000 })
    await page
        .getByRole('button', { name: 'Minimize' })
        .click({ timeout: 1000 })
        .catch(() => {})
}

test.describe('SQL editor typing performance', () => {
    test.describe.configure({ mode: 'serial' })
    test.setTimeout(180000)
    test.skip(!process.env.RUN_PERF_BENCH, 'Perf benchmark — run manually with RUN_PERF_BENCH=1')

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            skip_onboarding: true,
            use_current_time: true,
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
        await goToSqlEditor(page)
    })

    test('measure main-thread blocking while typing in a long query', async ({ page }, testInfo) => {
        const sqlInsight = new SqlInsight(page)
        const editorArea = page.getByTestId('hogql-query-editor')

        await test.step('load the long query into the editor', async () => {
            await sqlInsight.writeQuery(buildLargeQuery())
            // Let the initial parse + metadata request settle so warm-up cost is not measured.
            await page.waitForTimeout(2000)
        })

        await test.step('type a burst inside the leading comment and measure long tasks', async () => {
            await editorArea.click()
            await page.keyboard.press('ControlOrMeta+Home')
            await page.keyboard.press('End') // end of the first comment line — no autocomplete here

            await startMeasuring(page)
            await page.keyboard.type(TYPE_CHARS, { delay: TYPE_DELAY_MS })
            await page.waitForTimeout(600) // let any trailing debounced work run
            const stats = await stopMeasuring(page)

            // Prove the keystrokes actually landed in the editor.
            await expect(editorArea).toContainText(TYPE_MARKER)

            const summary =
                `keystrokes=${TYPE_CHARS.length} ` +
                `frameBlockedMs=${stats.frameBlockedMs} maxFrameGapMs=${stats.maxFrameGapMs} ` +
                `frames=${stats.frames} eventMaxMs=${stats.eventMaxMs} longTasks=${stats.longTasks}`
            testInfo.annotations.push({ type: 'typing-perf', description: summary })
            // eslint-disable-next-line no-console
            console.log(`\n[SQL editor typing perf] ${summary}\n`)
        })
    })
})
