import { Page } from '@playwright/test'

import { SqlInsight } from '../page-models/insights/sqlInsight'
import { expect, PlaywrightWorkspaceSetupResult, test } from '../utils/workspace-test-base'

// Manual performance benchmarks for the SQL editor on a long query: typing latency, and
// scroll latency. Not part of the CI suite (perf numbers are machine-dependent and would be
// flaky as an assertion) — gated behind RUN_PERF_BENCH so they are skipped unless run
// explicitly:
//
//   RUN_PERF_BENCH=1 BASE_URL='http://localhost:8010' \
//     pnpm --filter=@posthog/playwright exec playwright test sql-editor-typing-perf --workers 1
//
// Each test drives a fixed burst of input at a large query and reports main-thread long-task
// time via PerformanceObserver. To compare before/after a change, run it, `git stash` the
// change, run again, then `git stash pop` — the printed numbers are the result, not pass/fail.

// A recognizable, autocomplete-safe run of characters (no spaces/dots) typed into a comment.
const TYPE_MARKER = 'perfbenchmark'
const TYPE_CHARS = TYPE_MARKER.repeat(6) // 78 keystrokes
const TYPE_DELAY_MS = 40 // faster than the 150ms decoration debounce, so coalescing is visible

// Monaco emits a scroll event per wheel tick. Ticks land faster than a 60fps frame so that
// per-event work has to compete with painting, which is what makes coalescing measurable.
const SCROLL_TICKS = 60
const SCROLL_DELTA_PX = 120
const SCROLL_TICK_DELAY_MS = 8

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
    // Raw frame timestamps and labelled marks, so a single tick can be scored on its own. The
    // whole-burst aggregate above averages a one-off stall over 60 ticks and hides it — a 180ms
    // first tick reads as 3ms/tick, indistinguishable from noise.
    frameTimes: number[]
    marks: { label: string; t: number }[]
}

const FRAME_BUDGET_MS = 1000 / 60

/**
 * Blocked time and worst stall within a slice of the measured window. `frames` is reported so a
 * window that landed in the wrong place is obvious — a near-empty slice scores a flattering 0.
 */
function statsBetween(
    stats: TypingStats,
    from: number,
    to: number
): { blockedMs: number; maxGapMs: number; frames: number } {
    let blocked = 0
    let maxGap = 0
    let frames = 0
    for (let i = 1; i < stats.frameTimes.length; i++) {
        const t = stats.frameTimes[i]
        if (t < from || t > to) {
            continue
        }
        const gap = stats.frameTimes[i] - stats.frameTimes[i - 1]
        blocked += Math.max(0, gap - FRAME_BUDGET_MS)
        maxGap = Math.max(maxGap, gap)
        frames++
    }
    return { blockedMs: Math.round(blocked), maxGapMs: Math.round(maxGap), frames }
}

async function mark(page: Page, label: string): Promise<void> {
    await page.evaluate((l) => (window as any).__mark(l), label)
}

/**
 * Resolve once the main thread has been idle for `frames` consecutive frames, returning how long
 * that took. A fixed timeout either measures work that has not started yet or wastes time waiting;
 * the returned duration is itself a datum, being how long the editor stayed busy.
 */
async function waitForQuiescence(page: Page, frames = 30, maxGapMs = 20, timeoutMs = 30000): Promise<number> {
    return await page.evaluate(
        ([frameTarget, maxGap, timeout]) =>
            new Promise<number>((resolve) => {
                const start = performance.now()
                let quiet = 0
                let last = performance.now()
                const step = (t: number): void => {
                    const gap = t - last
                    last = t
                    quiet = gap <= maxGap ? quiet + 1 : 0
                    if (quiet >= frameTarget || performance.now() - start > timeout) {
                        resolve(Math.round(performance.now() - start))
                        return
                    }
                    requestAnimationFrame(step)
                }
                requestAnimationFrame(step)
            }),
        [frames, maxGapMs, timeoutMs]
    )
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

// The scroll benchmark needs a different shape of query than the typing one. The active-query
// outline overlay is repositioned on every scroll event and has to bound its whole range, so the
// cost scales with how many lines that range covers. The range is the *innermost SELECT
// containing the cursor* — and `findInnermostSelectAtOffset` returns null unless at least two
// SELECTs enclose the cursor, so a flat top-level query draws no outline at all and would measure
// nothing. Hence: a trivial outer SELECT wrapping a very long inner one, with the cursor parked
// inside the inner one. Must be syntactically valid HogQL or the outline never resolves; unknown
// column names are fine, since this only needs to parse, not resolve.
const SCROLL_QUERY_LINES = 900

function buildNestedLongQuery(): string {
    const columns = Array.from({ length: SCROLL_QUERY_LINES }, (_, i) => `        sum(metric_${i}) AS agg_${i}`).join(
        ',\n'
    )

    return `SELECT sub.agg_0\nFROM (\n    SELECT\n${columns}\n    FROM events\n) AS sub`
}

async function startMeasuring(page: Page): Promise<void> {
    await page.evaluate(() => {
        const w = window as any
        w.__frames = []
        w.__events = []
        w.__longTasks = []
        w.__marks = []
        w.__mark = (label: string): void => w.__marks.push({ label, t: performance.now() })
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
            frameTimes: frames,
            marks: w.__marks || [],
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

/**
 * Put the cursor immediately after the first occurrence of `needle`, via Monaco's own API.
 *
 * Keyboard navigation is not reliable for this: ControlOrMeta+End is Cmd+End on macOS, which Monaco
 * does not bind to end-of-document, so a "go to the end and walk up" sequence silently lands
 * somewhere near the top and the benchmark then edits whatever line it happened to find.
 */
async function placeCursorAfterText(page: Page, needle: string): Promise<number> {
    return await page.evaluate((text) => {
        const editor = (window as any).__monacoEditors?.at(-1)
        if (!editor) {
            throw new Error('Monaco handle missing — is __PERF_MONACO_HOOK__ set before load?')
        }
        const model = editor.getModel()
        for (let line = 1; line <= model.getLineCount(); line++) {
            const index = model.getLineContent(line).indexOf(text)
            if (index !== -1) {
                editor.focus()
                editor.setPosition({ lineNumber: line, column: index + text.length + 1 })
                editor.revealLineInCenter(line)
                return line
            }
        }
        throw new Error(`no line containing ${JSON.stringify(text)}`)
    }, needle)
}

test.describe('SQL editor performance', () => {
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
        // Exposes the Monaco instance so the benchmarks can place the cursor exactly and time
        // editor methods. Must run before any navigation, since the app reads it as it mounts.
        await page.addInitScript(() => {
            ;(window as any).__PERF_MONACO_HOOK__ = true
        })
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
        await goToSqlEditor(page)
    })

    test('measure main-thread blocking while typing in a long query', async ({ page }, testInfo) => {
        const sqlInsight = new SqlInsight(page)
        const editorArea = page.getByTestId('hogql-query-editor')

        await test.step('load the long query into the editor', async () => {
            await sqlInsight.writeQuery(buildLargeQuery())
            // Let the initial parse + metadata request settle so warm-up cost is not measured.
            await waitForQuiescence(page)
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

    test('measure main-thread blocking while scrolling a long query', async ({ page }, testInfo) => {
        const editorArea = page.getByTestId('hogql-query-editor')

        await test.step('load a long nested query into the editor', async () => {
            // Load via the editor's own `q` hash param instead of typing the query in. The editor
            // restores whichever query was last open, so writing into it is not reproducible — a
            // stale (and much larger) document from an earlier run gets measured instead.
            await page.goto('/sql#q=' + encodeURIComponent(buildNestedLongQuery()))
            await expect(page.getByTestId('editor-scene')).toBeVisible({ timeout: 60000 })
            await expect(editorArea).toBeVisible()
            // Let the initial parse + metadata request settle so warm-up cost is not measured.
            await waitForQuiescence(page)
        })

        await test.step('put the cursor inside the long inner SELECT', async () => {
            // Anywhere inside the inner SELECT will do — the outline then spans its ~900 lines.
            await placeCursorAfterText(page, 'AS agg_0')
        })

        await test.step('confirm the active-query outline is showing', async () => {
            // Without an active outline the scroll handler early-returns and this benchmark
            // measures nothing at all, so fail loudly rather than print a misleading 0.
            const outline = editorArea.locator('.active-query-outline')
            await expect(outline).toBeVisible({ timeout: 15000 })
        })

        await test.step('scroll a fixed burst and measure main-thread blocking', async () => {
            const box = await editorArea.boundingBox()
            expect(box).not.toBeNull()
            await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)

            await startMeasuring(page)
            for (let i = 0; i < SCROLL_TICKS; i++) {
                await mark(page, `tick-${i}`)
                await page.mouse.wheel(0, SCROLL_DELTA_PX)
                await page.waitForTimeout(SCROLL_TICK_DELAY_MS)
            }
            await mark(page, 'tick-end')
            await page.waitForTimeout(600) // let any trailing work run
            const stats = await stopMeasuring(page)

            // Score each tick on its own. The first tick after the editor has gone idle pays costs
            // the rest do not — a forced view render, a freshly invalidated layout — and the burst
            // total divides that by 60 until it looks like nothing.
            const markAt = (label: string): number => stats.marks.find((m) => m.label === label)?.t ?? 0
            const perTick = Array.from({ length: SCROLL_TICKS }, (_, i) =>
                statsBetween(stats, markAt(`tick-${i}`), markAt(i === SCROLL_TICKS - 1 ? 'tick-end' : `tick-${i + 1}`))
            )
            const firstTickBlockedMs = perTick[0].blockedMs
            const steadyBlockedMs = perTick.slice(1).reduce((sum, t) => sum + t.blockedMs, 0)

            const summary =
                `wheelTicks=${SCROLL_TICKS} ` +
                `frameBlockedMs=${stats.frameBlockedMs} maxFrameGapMs=${stats.maxFrameGapMs} ` +
                `frames=${stats.frames} eventMaxMs=${stats.eventMaxMs} longTasks=${stats.longTasks}`
            const perTickSummary =
                `firstTickBlockedMs=${firstTickBlockedMs} steadyBlockedMs=${steadyBlockedMs} ` +
                `steadyPerTickMs=${(steadyBlockedMs / (SCROLL_TICKS - 1)).toFixed(1)} ` +
                `worstTickMs=${Math.max(...perTick.map((t) => t.blockedMs))}`
            testInfo.annotations.push({ type: 'scroll-perf', description: `${summary} ${perTickSummary}` })
            // eslint-disable-next-line no-console
            console.log(`\n[SQL editor scroll perf] ${summary}\n[SQL editor scroll perf] ${perTickSummary}\n`)
        })
    })

    test('measure main-thread blocking on a cursor move and a single edit', async ({ page }, testInfo) => {
        // Both paths reach the HogQL parser, which runs over the whole query. A cursor move
        // changes no text at all, so any blocking there is pure waste; an edit has to reparse
        // once. Reported separately because they have different fixes and different budgets.
        const editorArea = page.getByTestId('hogql-query-editor')

        // Park just after the first column's alias, so the cursor-move phase's single ArrowDown
        // lands in the same column of the next line — the two lines are the same length — which is
        // just after `agg_1`. Typing there extends the alias to `agg_1x` and leaves the query valid.
        // That matters: an invalid query makes the parser fail fast, which reports as a perfect
        // score. (Appending at end-of-line instead would glue the character onto the *next*
        // column, which is exactly how this benchmark first measured a misleading zero.)
        // Note the outline only resolves with the cursor near the top of the range; the same
        // placement near the bottom leaves it hidden, which is worth a look on its own.

        await test.step('load a long nested query with the cursor inside the inner SELECT', async () => {
            await page.goto('/sql#q=' + encodeURIComponent(buildNestedLongQuery()))
            await expect(page.getByTestId('editor-scene')).toBeVisible({ timeout: 60000 })
            await expect(editorArea).toBeVisible()
            await waitForQuiescence(page)

            await placeCursorAfterText(page, 'AS agg_0')
            await expect(editorArea.locator('.active-query-outline')).toBeVisible({ timeout: 30000 })
            await waitForQuiescence(page)
        })

        await startMeasuring(page)

        // One action per phase, and the edit happens wherever the cursor move left us, so neither
        // phase has to reposition — repositioning is itself a cursor move, and its parse would land
        // in whichever window it happened to fall in.
        await test.step('move the cursor without changing any text', async () => {
            await mark(page, 'cursor-move')
            await page.keyboard.press('ArrowDown')
            await waitForQuiescence(page)
        })

        await test.step('type one character', async () => {
            await mark(page, 'edit')
            await page.keyboard.type('x')
            await waitForQuiescence(page)
            await mark(page, 'end')
        })

        const stats = await stopMeasuring(page)
        // A missing mark would silently produce a nonsense window (and a flattering 0), so refuse
        // to report rather than guess.
        const markAt = (label: string): number => {
            const found = stats.marks.find((m) => m.label === label)
            if (!found) {
                throw new Error(`benchmark mark '${label}' was never recorded`)
            }
            return found.t
        }
        const cursor = statsBetween(stats, markAt('cursor-move'), markAt('edit'))
        const edit = statsBetween(stats, markAt('edit'), markAt('end'))

        // Prove the keystroke landed where it was aimed. Without this an edit that missed the
        // editor — or hit the wrong line — reports as a perfect score. Checked against the model
        // rather than the DOM, since Monaco only renders the lines currently on screen.
        const edited = await page.evaluate(
            (needle) => (window as any).__monacoEditors.at(-1).getModel().getValue().includes(needle),
            'AS agg_1x,'
        )
        expect(edited, 'expected the typed character to extend the alias on the agg_1 line').toBe(true)

        const summary =
            `queryLines=${SCROLL_QUERY_LINES} ` +
            `cursorMoveBlockedMs=${cursor.blockedMs} cursorMoveMaxGapMs=${cursor.maxGapMs} ` +
            `cursorMoveFrames=${cursor.frames} ` +
            `editBlockedMs=${edit.blockedMs} editMaxGapMs=${edit.maxGapMs} editFrames=${edit.frames}`
        testInfo.annotations.push({ type: 'edit-perf', description: summary })
        // eslint-disable-next-line no-console
        console.log(`\n[SQL editor edit perf] ${summary}\n`)
    })
})
