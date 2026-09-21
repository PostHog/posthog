// Before/after benchmark for the SQL editor on a long query. Measures user-visible main-thread
// blocking on the three paths that matter, so a fix can be shown to help the edit/cursor paths
// without regressing the scroll path that PR #78998 fixed.
//
// Needs a local Storybook on :6006 (pnpm storybook).
//   node frontend/bin/bench-sql-editor.mjs --lines 900
//
// Reports, per phase, `blockedMs` (sum of each frame gap over the 16.7ms budget) and `maxGapMs`
// (the longest single stall — the number a user actually feels as a freeze).
import { readFileSync } from 'node:fs'
import { chromium } from 'playwright'

const args = Object.fromEntries(
    process.argv
        .slice(2)
        .join(' ')
        .split('--')
        .filter(Boolean)
        .map((s) => s.trim().split(/\s+/))
        .map(([k, v]) => [k, v ?? 'true'])
)
const LINES = parseInt(args.lines ?? '900', 10)
const SCROLL_TICKS = 60
// Storybook serves the app from vite, but the parser worker is a separate esbuild bundle served
// from /static in production, so Storybook 404s it and the manager silently falls back to the main
// thread. Serve a prebuilt bundle to the page so the worker path is the one measured. Build it with:
//   node_modules/.pnpm/esbuild@*/node_modules/esbuild/bin/esbuild \
//     frontend/src/scenes/data-warehouse/editor/hogqlParserWorker.ts \
//     --bundle --format=esm --outfile=/tmp/hogqlParserWorker.js
// Pass --no-worker to skip that and measure the fallback instead.
const WORKER_BUNDLE = args['no-worker'] ? null : (args.worker ?? '/tmp/hogqlParserWorker.js')

const STORY =
    'http://localhost:6006/iframe.html?id=scenes-app-data-warehouse-sql-editor--top-tools-per-server&viewMode=story'

// A trivial outer SELECT wrapping one very long inner SELECT, so two SELECTs enclose the cursor
// and the active-query outline draws (findInnermostSelectAtOffset returns null otherwise).
// The `-- edit target` line sits *inside* the inner SELECT: typing there keeps the query valid
// (an invalid query makes the parser fail fast and hides the very cost we are measuring) and
// keeps the cursor inside the inner SELECT so the outline stays up.
function buildQuery(lines) {
    const columns = Array.from({ length: lines }, (_, i) => `        sum(metric_${i}) AS agg_${i}`).join(',\n')
    return `SELECT sub.agg_0\nFROM (\n    SELECT\n${columns}\n        -- edit target\n    FROM events\n) AS sub`
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const FRAME_BUDGET = 1000 / 60

async function main() {
    const browser = await chromium.launch()
    const context = await browser.newContext({
        viewport: { width: 1600, height: 900 },
        permissions: ['clipboard-read', 'clipboard-write'],
    })
    const page = await context.newPage()
    await page.addInitScript(() => {
        window.__PERF_MONACO_HOOK__ = true
    })

    // Track worker creation so a silent fallback to the main thread cannot be mistaken for a fix.
    const createdWorkerUrls = []
    page.on('worker', (w) => createdWorkerUrls.push(w.url()))

    let workerBundleServed = 0
    if (WORKER_BUNDLE) {
        const body = readFileSync(WORKER_BUNDLE, 'utf8')
        await page.route('**/hogqlParserWorker.js', async (route) => {
            workerBundleServed++
            await route.fulfill({ body, contentType: 'text/javascript' })
        })
    }

    await page.goto(STORY, { waitUntil: 'load', timeout: 120000 })
    await page.waitForSelector('.monaco-editor', { timeout: 120000 })
    await page.waitForFunction(() => (window.__monacoEditors ?? []).length > 0, { timeout: 60000 })

    await page.evaluate(() => {
        const w = window
        w.__ed = () => w.__monacoEditors[w.__monacoEditors.length - 1]
        // Resolve once N consecutive frames come in under budget, i.e. the main thread went idle.
        w.__quiesce = (frames = 30, maxGapMs = 20, timeoutMs = 60000) =>
            new Promise((resolve) => {
                const start = performance.now()
                let quiet = 0
                let last = performance.now()
                const step = (t) => {
                    const gap = t - last
                    last = t
                    quiet = gap <= maxGapMs ? quiet + 1 : 0
                    if (quiet >= frames || performance.now() - start > timeoutMs) {
                        resolve(Math.round(performance.now() - start))
                        return
                    }
                    requestAnimationFrame(step)
                }
                requestAnimationFrame(step)
            })
        w.__start = () => {
            w.__frames = []
            w.__marks = []
            w.__mark = (label) => w.__marks.push({ label, t: performance.now() })
            const loop = (t) => {
                w.__frames.push(t)
                w.__raf = requestAnimationFrame(loop)
            }
            w.__raf = requestAnimationFrame(loop)
        }
        w.__stop = () => {
            cancelAnimationFrame(w.__raf)
            return { frames: w.__frames, marks: w.__marks }
        }
    })

    // Load the fixture by clipboard paste. keyboard.insertText is treated as typed input, so
    // Monaco re-indents every line and the indentation compounds (a 32KB fixture lands as a 3.2MB
    // document of whitespace); setValue/executeEdits gets reverted because `value` is kea-controlled.
    const query = buildQuery(LINES)
    for (let attempt = 1; attempt <= 4; attempt++) {
        await page.evaluate(async (q) => await navigator.clipboard.writeText(q), query)
        await page.evaluate(() => window.__ed().focus())
        await sleep(300)
        await page.keyboard.press('ControlOrMeta+a')
        await page.keyboard.press('ControlOrMeta+v')
        try {
            await page.waitForFunction((n) => window.__ed().getModel().getValueLength() === n, query.length, {
                timeout: 20000,
            })
            break
        } catch {
            if (attempt === 4) {
                throw new Error('fixture never landed cleanly')
            }
        }
    }

    // Park the cursor at the end of the `-- edit target` line, inside the inner SELECT.
    const editLine = query.split('\n').findIndex((l) => l.includes('-- edit target')) + 1
    await page.evaluate((line) => {
        const ed = window.__ed()
        ed.focus()
        ed.setPosition({ lineNumber: line, column: ed.getModel().getLineMaxColumn(line) })
    }, editLine)

    // Wait for the outline itself, not for the main thread to go quiet. Once the parse runs in a
    // worker the main thread goes quiet almost immediately, long before the result arrives.
    await page
        .waitForFunction(() => document.querySelector('.active-query-outline')?.style.display === 'block', undefined, {
            timeout: 120000,
        })
        .catch(() => {})
    await page.evaluate(() => window.__quiesce(45, 20, 120000))
    await sleep(1000)

    const outline = await page.evaluate(() => {
        const n = document.querySelector('.active-query-outline')
        return n ? { display: n.style.display, height: n.style.height } : null
    })
    if (outline?.display !== 'block') {
        throw new Error(`no outline drawn — benchmark would measure the wrong thing: ${JSON.stringify(outline)}`)
    }

    await page.evaluate(() => window.__start())

    // Phase 1 — cursor move only, no edit. Nothing about the document changed.
    await page.evaluate(() => window.__quiesce())
    await page.evaluate(() => window.__mark('cursor-move'))
    await page.keyboard.press('ArrowUp')
    const cursorQuiesceMs = await page.evaluate(() => window.__quiesce())

    // Phase 2 — one keystroke inside the comment, document stays valid. Moving the parse off the
    // main thread trades a freeze for latency, so time how long the outline takes to catch up too.
    // Re-park the cursor at the end of the edit-target comment. Phase 1's ArrowUp leaves it partway
    // along a much longer column line, and pressing Enter there splits an expression in two, which
    // makes the query invalid — the parser then fails fast and the phase measures nothing.
    await page.evaluate((line) => {
        const ed = window.__ed()
        ed.focus()
        ed.setPosition({ lineNumber: line, column: ed.getModel().getLineMaxColumn(line) })
    }, editLine)
    await page.evaluate(() => window.__quiesce())
    await sleep(1500)

    // Pressing Enter adds a line inside the inner SELECT, so the outline's own height has to grow
    // by one line. Watching for that (rather than any style change, which a scroll also causes)
    // is what proves the parse result actually came back and was applied.
    const heightBeforeEdit = await page.evaluate(() => document.querySelector('.active-query-outline').style.height)
    await page.evaluate(() => window.__mark('edit'))
    const editAt = Date.now()
    await page.keyboard.press('Enter')
    const editQuiesceMs = await page.evaluate(() => window.__quiesce())
    let outlineUpdateMs = null
    for (let i = 0; i < 300; i++) {
        const h = await page.evaluate(() => document.querySelector('.active-query-outline').style.height)
        if (h !== heightBeforeEdit) {
            outlineUpdateMs = Date.now() - editAt
            break
        }
        await sleep(100)
    }

    // Phase 3 — the scroll burst PR #78998 fixed. Must not regress.
    await page.evaluate(() => window.__ed().setScrollTop(0))
    await sleep(500)
    const box = await page.locator('.monaco-editor').first().boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.evaluate(() => window.__quiesce())
    for (let i = 0; i < SCROLL_TICKS; i++) {
        await page.evaluate((n) => window.__mark(`scroll-${n}`), i)
        await page.mouse.wheel(0, 120)
        await sleep(8)
    }
    await page.evaluate(() => window.__mark('scroll-end'))
    await sleep(600)

    const raw = await page.evaluate(() => window.__stop())
    await browser.close()

    const slice = (from, to) => {
        let blocked = 0
        let maxGap = 0
        for (let i = 1; i < raw.frames.length; i++) {
            const t = raw.frames[i]
            if (t < from || t > to) {
                continue
            }
            const gap = raw.frames[i] - raw.frames[i - 1]
            blocked += Math.max(0, gap - FRAME_BUDGET)
            maxGap = Math.max(maxGap, gap)
        }
        return { blockedMs: Math.round(blocked), maxGapMs: Math.round(maxGap) }
    }
    const at = (label) => raw.marks.find((m) => m.label === label)?.t
    const seg = (label, next) => slice(at(label), next ? at(next) : Infinity)

    const scrollTicks = Array.from({ length: SCROLL_TICKS }, (_, i) =>
        slice(at(`scroll-${i}`), at(i === SCROLL_TICKS - 1 ? 'scroll-end' : `scroll-${i + 1}`))
    )
    const scrollTotal = scrollTicks.reduce((a, s) => a + s.blockedMs, 0)

    console.info(
        JSON.stringify(
            {
                lines: LINES,
                chars: query.length,
                outlineHeight: outline.height,
                parserWorker: {
                    requested: !!WORKER_BUNDLE,
                    bundleServed: workerBundleServed,
                    created: createdWorkerUrls.filter((u) => u.includes('hogqlParserWorker')).length,
                },
                cursorMove: { ...seg('cursor-move', 'edit'), settleMs: cursorQuiesceMs },
                edit: {
                    ...seg('edit', 'scroll-0'),
                    settleMs: editQuiesceMs,
                    // How long until the outline reflects the edit. Blocking work makes this small
                    // but freezes the UI; off-thread work makes it larger and keeps the UI alive.
                    outlineUpdateMs,
                },
                scroll: {
                    blockedMs: scrollTotal,
                    maxGapMs: Math.max(...scrollTicks.map((s) => s.maxGapMs)),
                    firstTickBlockedMs: scrollTicks[0].blockedMs,
                    steadyBlockedMs: scrollTotal - scrollTicks[0].blockedMs,
                },
            },
            null,
            1
        )
    )
}

main().catch((e) => {
    console.error('FAILED:', e.message)
    process.exit(1)
})
