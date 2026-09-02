// Diagnostic driver for the SQL editor "initial scroll delay". Not part of any suite —
// throwaway harness, run against a local Storybook (pnpm storybook) on :6006.
//
//   node frontend/bin/diagnose-first-scroll.mjs --lines 900 --arm baseline
//
// Arms: baseline | no-outline | no-sticky | no-folding | no-wrap | stub-hpos | stub-vpos | no-border
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
const ARM = args.arm ?? 'baseline'
const PROFILE = args.profile === 'true'

const STORY =
    'http://localhost:6006/iframe.html?id=scenes-app-data-warehouse-sql-editor--top-tools-per-server&viewMode=story'

// Same shape as the playwright benchmark fixture: a trivial outer SELECT wrapping one very long
// inner SELECT, so `findInnermostSelectAtOffset` finds two enclosing SELECTs and the outline draws.
// Leading comment line is an autocomplete-safe place to type.
function buildQuery(lines) {
    const columns = Array.from({ length: lines }, (_, i) => `        sum(metric_${i}) AS agg_${i}`).join(',\n')
    return `-- edit target top\nSELECT sub.agg_0\nFROM (\n    SELECT\n${columns}\n    FROM events\n) AS sub`
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

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
    if (ARM === 'no-mutobs') {
        await page.addInitScript(() => {
            const orig = MutationObserver.prototype.observe
            MutationObserver.prototype.observe = function (target, opts) {
                if (target === document.body && opts?.subtree && opts?.childList) {
                    return
                }
                return orig.call(this, target, opts)
            }
        })
    }

    const errors = []
    page.on('pageerror', (e) => errors.push(String(e)))

    await page.goto(STORY, { waitUntil: 'load', timeout: 120000 })
    await page.waitForSelector('.monaco-editor', { timeout: 120000 })
    await page.waitForFunction(() => (window.__monacoEditors ?? []).length > 0, { timeout: 60000 })

    // In-page helpers.
    await page.evaluate(() => {
        const w = window
        w.__ed = () => w.__monacoEditors[w.__monacoEditors.length - 1]
        w.__quiesce = (frames = 30, maxGapMs = 20, timeoutMs = 20000) =>
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
            w.__longTasks = []
            w.__mark = (label) => w.__marks.push({ label, t: performance.now() })
            const loop = (t) => {
                w.__frames.push(t)
                w.__raf = requestAnimationFrame(loop)
            }
            w.__raf = requestAnimationFrame(loop)
            w.__ltObs = new PerformanceObserver((l) => {
                for (const e of l.getEntries()) {
                    w.__longTasks.push({ startTime: e.startTime, duration: e.duration })
                }
            })
            w.__ltObs.observe({ type: 'longtask' })
        }
        w.__stop = () => {
            cancelAnimationFrame(w.__raf)
            w.__ltObs?.disconnect()
            return { frames: w.__frames, marks: w.__marks, longTasks: w.__longTasks }
        }
    })

    // Load the fixture through the real edit path. Setting the model directly does not stick —
    // the editor's `value` prop is controlled by kea, so the next render reverts it. The paste
    // occasionally lands before Monaco has focus, so verify and retry.
    // Load the fixture by clipboard paste. The two obvious alternatives both fail: keyboard
    // insertText is treated as typed input, so Monaco re-indents every line and the indentation
    // compounds (a 32KB fixture lands as a 3.2MB document of leading whitespace), and
    // setValue/executeEdits gets reverted a beat later because the editor's `value` prop is
    // controlled by kea.
    const query = buildQuery(LINES)
    const wantChars = query.length
    for (let attempt = 1; attempt <= 4; attempt++) {
        await page.evaluate(async (q) => await navigator.clipboard.writeText(q), query)
        await page.evaluate(() => window.__ed().focus())
        await sleep(300)
        await page.keyboard.press('ControlOrMeta+a')
        await page.keyboard.press('ControlOrMeta+v')
        try {
            await page.waitForFunction((n) => window.__ed().getModel().getValueLength() === n, wantChars, {
                timeout: 15000,
            })
            break
        } catch {
            if (attempt === 4) {
                const got = await page.evaluate(() => window.__ed().getModel().getValueLength())
                throw new Error(`fixture never landed cleanly: wanted ${wantChars} chars, got ${got}`)
            }
        }
    }
    await page.evaluate(() => window.__quiesce(45, 20, 25000))
    await sleep(1500)

    // Park the cursor. Line 1 is the comment, 2 `SELECT sub.agg_0`, 3 `FROM (`, 4 `SELECT`,
    // 5+ the columns. Line 6 sits inside the inner SELECT (outline draws); line 2 sits in the
    // outer one only, where findInnermostSelectAtOffset returns null (no outline).
    const cursorLine = ARM === 'no-outline' ? 2 : 6
    await page.evaluate((line) => {
        const ed = window.__ed()
        ed.focus()
        ed.setPosition({ lineNumber: line, column: ed.getModel().getLineMaxColumn(line) })
    }, cursorLine)
    if (ARM !== 'no-outline') {
        await page
            .waitForFunction(
                () => document.querySelector('.active-query-outline')?.style.display === 'block',
                undefined,
                { timeout: 30000 }
            )
            .catch(() => {})
    }
    await sleep(1200)

    const outlineCount = await page.locator('.active-query-outline').count()
    const outlineBox = await page
        .evaluate(() => {
            const n = document.querySelector('.active-query-outline')
            return n ? { h: n.style.height, display: n.style.display } : null
        })
        .catch(() => null)
    if (ARM !== 'no-outline' && (!outlineCount || outlineBox?.display === 'none')) {
        const d = await page.evaluate(() => ({
            diag: window.__diag ?? 'decoration path NEVER RAN',
            lines: window.__ed().getModel().getLineCount(),
            pos: window.__ed().getPosition(),
            visible: window.__ed().getVisibleRanges(),
        }))
        throw new Error(
            `no active-query outline drawn (count=${outlineCount} box=${JSON.stringify(outlineBox)}) ${JSON.stringify(d)}`
        )
    }
    if (ARM === 'no-outline' && outlineBox && outlineBox.display !== 'none') {
        throw new Error('expected no outline for the no-outline arm')
    }

    // Arm-specific toggles.
    if (ARM === 'no-sticky') {
        await page.evaluate(() => window.__ed().updateOptions({ stickyScroll: { enabled: false } }))
    }
    if (ARM === 'no-folding') {
        await page.evaluate(() => window.__ed().updateOptions({ folding: false }))
    }
    if (ARM === 'no-wrap') {
        await page.evaluate(() => window.__ed().updateOptions({ wordWrap: 'off' }))
    }
    if (ARM === 'stub-hpos') {
        await page.evaluate(() => {
            window.__ed().getScrolledVisiblePosition = () => ({ left: 0, top: 0, height: 18 })
        })
    }
    if (ARM === 'stub-vpos') {
        await page.evaluate(() => {
            const ed = window.__ed()
            ed.getTopForPosition = () => 0
            ed.getBottomForLineNumber = () => 400
        })
    }
    if (ARM === 'no-border') {
        await page.addStyleTag({ content: '.active-query-outline { border: none !important; }' })
    }

    const editorArea = page.locator('.monaco-editor').first()
    const box = await editorArea.boundingBox()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)

    const threeFrames = () =>
        page.evaluate(
            () =>
                new Promise((r) =>
                    requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(() => r())))
                )
        )

    // Instrument the editor methods renderQueryOutline calls, so a spike can be attributed to
    // one of them without a profile.
    await page.evaluate(() => {
        const ed = window.__ed()
        window.__t = {}
        for (const m of ['getScrolledVisiblePosition', 'getTopForPosition', 'getBottomForLineNumber']) {
            const orig = ed[m].bind(ed)
            window.__t[m] = { n: 0, ms: 0, max: 0 }
            ed[m] = (...a) => {
                const t0 = performance.now()
                try {
                    return orig(...a)
                } finally {
                    const d = performance.now() - t0
                    const s = window.__t[m]
                    s.n++
                    s.ms += d
                    if (d > s.max) {
                        s.max = d
                    }
                }
            }
        }
    })

    // ---- cold first tick, straight after load ----
    await page.evaluate(() => window.__start())
    await page.evaluate(() => window.__mark('cold-tick'))
    await page.mouse.wheel(0, 120)
    await threeFrames()
    // ---- warm up, then a warm single tick as the baseline ----
    for (let i = 0; i < 15; i++) {
        await page.mouse.wheel(0, 120)
        await sleep(8)
    }
    await page.evaluate(() => window.__quiesce())
    await page.evaluate(() => window.__mark('warm-tick'))
    await page.mouse.wheel(0, 120)
    await threeFrames()
    await page.evaluate(() => window.__quiesce())

    // ---- the edit, then a no-scroll window (E1), then the first post-edit tick ----
    await page.evaluate(() => (window.__tReset = JSON.parse(JSON.stringify(window.__t))))
    let profile = null
    let cdp = null
    if (PROFILE) {
        cdp = await context.newCDPSession(page)
        await cdp.send('Profiler.enable')
        await cdp.send('Profiler.setSamplingInterval', { interval: 50 })
        await cdp.send('Profiler.start')
    }
    await page.evaluate(() => window.__mark('edit'))
    await page.keyboard.type('x') // inside `... AS agg_N` — no space/dot, so no autocomplete
    await page.evaluate(() => window.__mark('post-edit-no-scroll'))
    await sleep(1500) // E1: does the spike land here, with zero wheel events?
    const quiesceMs = await page.evaluate(() => window.__quiesce())
    if (PROFILE) {
        // The profile brackets the keystroke and everything its debounces trigger — no scroll.
        profile = (await cdp.send('Profiler.stop')).profile
    }
    await page.evaluate(() => window.__mark('post-edit-tick-0'))
    await page.mouse.wheel(0, 120)
    await threeFrames()
    for (let i = 1; i <= 5; i++) {
        await page.evaluate((n) => window.__mark(`post-edit-tick-${n}`), i)
        await page.mouse.wheel(0, 120)
        await threeFrames()
    }

    // A far jump reveals lines Monaco has never rendered or tokenized, unlike a 120px nudge.
    await page.evaluate(() => window.__quiesce())
    await page.evaluate(() => window.__mark('warm-bigjump'))
    await page.mouse.wheel(0, 20000)
    await threeFrames()
    await page.evaluate(() => window.__quiesce())
    await page.evaluate(() => window.__mark('edit2'))
    await page.keyboard.type('y')
    await page.evaluate(() => window.__quiesce())
    await page.evaluate(() => window.__mark('post-edit-bigjump'))
    await page.mouse.wheel(0, 20000)
    await threeFrames()
    await sleep(400)

    const raw = await page.evaluate(() => window.__stop())
    const methodTimes = await page.evaluate(() => ({ all: window.__t, atEdit: window.__tReset }))
    const parseTimes = await page.evaluate(() => window.__parseTimes ?? [])
    await browser.close()

    // ---- attribution ----
    const FRAME_BUDGET = 1000 / 60
    const slice = (from, to) => {
        let blocked = 0
        let maxGap = 0
        let n = 0
        for (let i = 1; i < raw.frames.length; i++) {
            const t = raw.frames[i]
            if (t < from || t > to) {
                continue
            }
            const gap = raw.frames[i] - raw.frames[i - 1]
            blocked += Math.max(0, gap - FRAME_BUDGET)
            maxGap = Math.max(maxGap, gap)
            n++
        }
        return { blockedMs: Math.round(blocked), maxGapMs: Math.round(maxGap), frames: n }
    }
    const segments = {}
    for (let i = 0; i < raw.marks.length; i++) {
        const from = raw.marks[i].t
        const to = raw.marks[i + 1]?.t ?? Infinity
        segments[raw.marks[i].label] = slice(from, to)
    }
    const perMethod = {}
    for (const k of Object.keys(methodTimes.all)) {
        perMethod[k] = {
            calls: methodTimes.all[k].n - methodTimes.atEdit[k].n,
            ms: +(methodTimes.all[k].ms - methodTimes.atEdit[k].ms).toFixed(2),
            maxMs: +methodTimes.all[k].max.toFixed(2),
        }
    }

    const out = {
        lines: LINES,
        arm: ARM,
        outlineHeight: outlineBox?.h ?? null,
        quiesceAfterEditMs: quiesceMs,
        segments,
        longTasks: raw.longTasks.map((l) => Math.round(l.duration)),
        methodTimesSinceEdit: perMethod,
        pageErrors: errors.slice(0, 3),
        parseTimes,
    }
    if (profile) {
        const byId = new Map(profile.nodes.map((n) => [n.id, n]))
        const self = new Map()
        for (let i = 0; i < profile.samples.length; i++) {
            const n = byId.get(profile.samples[i])
            if (!n) {
                continue
            }
            const cf = n.callFrame
            const key = `${cf.functionName || '(anon)'} @ ${(cf.url || '').split('/').pop()}:${cf.lineNumber}`
            self.set(key, (self.get(key) ?? 0) + (profile.timeDeltas[i] ?? 0) / 1000)
        }
        out.selfTimeTop = [...self]
            .map(([fn, ms]) => ({ fn, ms: +ms.toFixed(1) }))
            .sort((a, b) => b.ms - a.ms)
            .slice(0, 25)
    }
    console.info(JSON.stringify(out, null, 1))
}

main().catch((e) => {
    console.error('FAILED:', e.message)
    process.exit(1)
})
