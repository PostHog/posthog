// Captures the stills of a UI flow for reel-render.mjs.
// Drives a Storybook story, or a page of the local app in a new demo workspace, with real mouse input,
// takes a screenshot before each step and one at the end, and records where each step points.
//
// Usage: node reel-capture.mjs <shot-list.json> <out-dir>
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

// Resolve Playwright from the PostHog checkout the command runs in, since the skill can live outside it.
const { chromium } = createRequire(path.join(process.cwd(), 'package.json'))('playwright')

// LOADER_SELECTORS in common/storybook/.storybook/test-runner.ts, without toasts:
// a toast can be the result that a step shows.
const LOADER_SELECTORS = [
    '.Spinner',
    '.quill-spinner',
    '.LemonSkeleton',
    '.LemonTableLoader',
    '[aria-busy="true"]',
    '.SessionRecordingPlayer--buffering',
    '.Lettermark--unknown',
    '[data-attr="loading-bar"]',
]
const ACTIONS = ['click', 'rightclick', 'hover']
// reel-render.mjs zooms up to 1.9x at 2x device pixels, so 3x stills keep text sharp at full zoom.
const CAPTURE_SCALE = 3
const FIRST_LOAD_TIMEOUT_MS = 300_000
const STEP_TIMEOUT_MS = 20_000
const QUIET_MS = 1500
const SETTLE_MS = 600
// Workspace setup generates demo data, which takes seconds on a healthy stack.
const SETUP_TIMEOUT_MS = 120_000
// setup_test creates users and a full-scope API key, so it must never reach another instance.
const LOOPBACK_HOSTS = ['localhost', '127.0.0.1', '[::1]']

function locate(page, target) {
    let scope = page.locator('body')
    if (target.within) {
        scope = scope.locator(target.within)
    }
    if (target.label) {
        return scope.getByLabel(target.label, { exact: true }).first()
    }
    if (target.text && target.within) {
        // The `within` element that holds an element with exactly this text, such as a list row.
        return scope.filter({ has: page.getByText(target.text, { exact: true }) }).first()
    }
    if (target.text) {
        return scope.getByText(target.text, { exact: true }).first()
    }
    return scope.locator(target.selector).first()
}

async function settle(page, timeout) {
    // Lazy scenes mount their spinner late, so wait for a quiet stretch, not one clean check.
    await page.evaluate(() => {
        window.__reelQuietSince = undefined
    })
    await page.waitForFunction(
        ({ selector, quietMs }) => {
            const busy = [...document.querySelectorAll(selector)].some((el) => el.checkVisibility())
            if (busy) {
                window.__reelQuietSince = undefined
                return false
            }
            window.__reelQuietSince ??= performance.now()
            return performance.now() - window.__reelQuietSince > quietMs
        },
        { selector: LOADER_SELECTORS.join(','), quietMs: QUIET_MS },
        { timeout, polling: 100 }
    )
    await page.evaluate(() => document.fonts.ready)
    // Menus and hover cards open on short timers.
    await page.waitForTimeout(SETTLE_MS)
}

async function boxOf(locator) {
    const box = await locator.boundingBox()
    if (!box) {
        throw new Error('The target has no bounding box. Is it hidden?')
    }
    return { x: box.x, y: box.y, w: box.width, h: box.height }
}

async function act(page, action, point) {
    await page.mouse.move(point.x, point.y)
    if (action === 'click') {
        await page.mouse.click(point.x, point.y)
    } else if (action === 'rightclick') {
        await page.mouse.click(point.x, point.y, { button: 'right' })
    }
}

// The run-posthog recipe: create a workspace with generated demo data, then log in from the page,
// so Django's CSRF check sees the page's cookies. Works only on a local stack with DEBUG.
async function logInToTestWorkspace(page, origin) {
    await page.goto(`${origin}/login`, { timeout: FIRST_LOAD_TIMEOUT_MS })
    const result = await page.evaluate(async (timeoutMs) => {
        const post = (path, body) =>
            fetch(path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal: AbortSignal.timeout(timeoutMs),
            })
        let setup
        try {
            // Current time keeps the demo data inside the default date ranges of scenes such as replay.
            setup = await post('/api/setup_test/organization_with_team/', {
                skip_onboarding: true,
                use_current_time: true,
            })
        } catch (error) {
            return { error: `setup_test failed: ${error.name}` }
        }
        if (!setup.ok) {
            return { error: `setup_test returned ${setup.status}` }
        }
        const workspace = (await setup.json()).result
        let login
        try {
            login = await post('/api/login/', { email: workspace.user_email, password: '12345678' })
        } catch (error) {
            return { error: `login failed: ${error.name}` }
        }
        if (!login.ok) {
            return { error: `login returned ${login.status}` }
        }
        return { teamId: workspace.team_id }
    }, SETUP_TIMEOUT_MS)
    if (result.error) {
        throw new Error(`Could not create the test workspace: ${result.error}. Is this a local stack with DEBUG?`)
    }
    return result.teamId
}

async function main() {
    const [shotListPath, outDir] = process.argv.slice(2)
    if (!shotListPath || !outDir) {
        throw new Error('Usage: node reel-capture.mjs <shot-list.json> <out-dir>')
    }
    const shotList = JSON.parse(readFileSync(shotListPath, 'utf8'))
    const viewport = shotList.viewport ?? { width: 1280, height: 800 }
    // Check before the first load, which can take minutes on a cold server.
    for (const step of shotList.steps) {
        if (!ACTIONS.includes(step.action)) {
            throw new Error(`Unknown action "${step.action}". Use ${ACTIONS.join(', ')}.`)
        }
    }
    if (shotList.testWorkspace) {
        if (!LOOPBACK_HOSTS.includes(new URL(shotList.url).hostname)) {
            throw new Error('testWorkspace needs a url on localhost, so setup never reaches another instance.')
        }
        if (!shotList.url.includes('{team_id}')) {
            throw new Error('testWorkspace needs {team_id} in the url, so the reel opens the demo workspace.')
        }
    }
    mkdirSync(outDir, { recursive: true })

    const browser = await chromium.launch()
    const context = await browser.newContext({ viewport, deviceScaleFactor: CAPTURE_SCALE, reducedMotion: 'reduce' })
    const page = await context.newPage()
    let url = shotList.url
    if (shotList.testWorkspace) {
        const teamId = await logInToTestWorkspace(page, new URL(url).origin)
        url = url.replace('{team_id}', String(teamId))
    }
    // A cold Vite dev server compiles each lazy chunk on its first request, which can take minutes.
    await page.goto(url, { timeout: FIRST_LOAD_TIMEOUT_MS })
    await settle(page, FIRST_LOAD_TIMEOUT_MS)

    const frames = []
    const snap = async (caption, target) => {
        const file = `${String(frames.length).padStart(2, '0')}.png`
        await page.screenshot({ path: path.join(outDir, file) })
        const frame = { file, caption: caption ?? null, target }
        frames.push(frame)
        return frame
    }

    for (const step of shotList.steps) {
        const locator = locate(page, step.target)
        await locator.waitFor({ state: 'visible', timeout: STEP_TIMEOUT_MS })
        // page.mouse works in viewport coordinates, so a target below the fold must scroll in first.
        await locator.scrollIntoViewIfNeeded({ timeout: STEP_TIMEOUT_MS })
        const box = await boxOf(locator)
        const point = step.at
            ? { x: box.x + step.at.x, y: box.y + step.at.y }
            : { x: box.x + box.w / 2, y: box.y + box.h / 2 }
        const frame = await snap(step.caption, { ...box, point, action: step.action })
        await act(page, step.action, point)
        if (step.waitFor) {
            await locate(page, step.waitFor).waitFor({ state: 'visible', timeout: STEP_TIMEOUT_MS })
        }
        await settle(page, STEP_TIMEOUT_MS)
        if (step.focus) {
            frame.target.result = await boxOf(locate(page, step.focus))
        }
    }
    await snap(shotList.finalCaption, null)
    await browser.close()

    writeFileSync(path.join(outDir, 'frames.json'), JSON.stringify({ viewport, frames }, null, 2))
    process.stdout.write(`${outDir}: ${frames.length} stills\n`)
}

await main()
