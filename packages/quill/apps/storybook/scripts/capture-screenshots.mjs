#!/usr/bin/env node
/* eslint-disable no-console */
import { chromium } from 'playwright-core'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const STATIC_DIR = resolve(__dirname, '../storybook-static')
const OUT_DIR = process.env.SB_OUT_DIR
    ? resolve(process.env.SB_OUT_DIR)
    : resolve(__dirname, '../__screenshots__/baseline')
const BASE_URL = process.env.SB_URL || 'http://127.0.0.1:6006'
const THEMES = ['light', 'dark']
const VIEWPORT = { width: 1280, height: 800 }
const CONCURRENCY = Number(process.env.SB_CONCURRENCY || 4)
const STORY_TIMEOUT_MS = 15000

function findChromiumExecutable() {
    // Try Playwright's packaged Chromium first, else fall back to system Chrome
    const envPath = process.env.CHROME_EXECUTABLE_PATH
    if (envPath) {
        return envPath
    }
    return undefined
}

async function main() {
    const indexJson = JSON.parse(await readFile(resolve(STATIC_DIR, 'index.json'), 'utf8'))
    const entries = Object.values(indexJson.entries || {}).filter((e) => e.type === 'story')
    if (!entries.length) {
        throw new Error('No stories found in index.json')
    }
    console.log(`Found ${entries.length} stories. Capturing ${entries.length * THEMES.length} screenshots (${THEMES.length} themes).`)

    await Promise.all(THEMES.map((t) => mkdir(resolve(OUT_DIR, t), { recursive: true })))

    const browser = await chromium.launch({
        headless: true,
        executablePath: findChromiumExecutable(),
        args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
    })

    const manifest = {
        capturedAt: new Date().toISOString(),
        viewport: VIEWPORT,
        themes: THEMES,
        count: entries.length,
        stories: {},
    }

    let done = 0
    const failures = []

    async function captureOne(entry, theme, attempt = 1) {
        const ctx = await browser.newContext({
            viewport: VIEWPORT,
            deviceScaleFactor: 1,
            colorScheme: theme === 'dark' ? 'dark' : 'light',
        })
        const page = await ctx.newPage()
        try {
            const url = `${BASE_URL}/iframe.html?viewMode=story&globals=theme:${theme}&id=${encodeURIComponent(entry.id)}`
            await page.goto(url, { waitUntil: 'load', timeout: STORY_TIMEOUT_MS })
            // Force theme: storybook applies theme via decorator, which listens to globals.theme
            // Add fallback: set .dark class + theme attr directly on <html>
            await page.evaluate((t) => {
                const el = document.documentElement
                if (t === 'dark') {
                    el.classList.add('dark')
                    el.setAttribute('theme', 'dark')
                } else {
                    el.classList.remove('dark')
                    el.removeAttribute('theme')
                }
            }, theme)
            // Wait for fonts + any story-level async rendering
            await page.evaluate(() => document.fonts?.ready)
            await page.waitForTimeout(250)

            // Detect storybook runtime errors and retry (race vs static server ready-state)
            const errorText = await page.evaluate(() => {
                const body = document.body?.textContent || ''
                if (/Failed to fetch|TypeError: Failed to fetch|Unable to preload CSS/i.test(body)) {
                    return body.slice(0, 120)
                }
                return null
            })
            if (errorText && attempt < 3) {
                await ctx.close()
                await new Promise((r) => setTimeout(r, 400 * attempt))
                return captureOne(entry, theme, attempt + 1)
            }

            const file = resolve(OUT_DIR, theme, `${entry.id}.png`)
            await page.screenshot({ path: file, fullPage: true, animations: 'disabled', caret: 'hide' })
            return { file, ok: true, attempt }
        } catch (err) {
            if (attempt < 3) {
                await ctx.close()
                await new Promise((r) => setTimeout(r, 400 * attempt))
                return captureOne(entry, theme, attempt + 1)
            }
            return { ok: false, error: err.message }
        } finally {
            try {
                await ctx.close()
            } catch {}
        }
    }

    const queue = []
    for (const entry of entries) {
        for (const theme of THEMES) {
            queue.push({ entry, theme })
        }
    }

    async function worker() {
        while (queue.length) {
            const item = queue.shift()
            if (!item) {return}
            const { entry, theme } = item
            const r = await captureOne(entry, theme)
            done++
            if (r.ok) {
                if (!manifest.stories[entry.id]) {
                    manifest.stories[entry.id] = {
                        id: entry.id,
                        title: entry.title,
                        name: entry.name,
                        importPath: entry.importPath,
                        screenshots: {},
                    }
                }
                manifest.stories[entry.id].screenshots[theme] = `${theme}/${entry.id}.png`
                process.stdout.write(`[${done}/${queue.length + done}] ${theme} ${entry.id}\n`)
            } else {
                failures.push({ id: entry.id, theme, error: r.error })
                process.stdout.write(`[FAIL ${done}] ${theme} ${entry.id} — ${r.error}\n`)
            }
        }
    }

    await Promise.all(Array.from({ length: CONCURRENCY }, () => worker()))
    await browser.close()

    manifest.failures = failures
    await writeFile(resolve(OUT_DIR, 'manifest.json'), JSON.stringify(manifest, null, 2))
    console.log(`\nDone. Captured ${Object.keys(manifest.stories).length} stories. Failures: ${failures.length}`)
    if (failures.length) {
        console.log('First 5 failures:')
        failures.slice(0, 5).forEach((f) => console.log(` - ${f.theme} ${f.id}: ${f.error}`))
    }
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
