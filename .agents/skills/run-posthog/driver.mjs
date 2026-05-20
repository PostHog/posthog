#!/usr/bin/env node
// Smoke driver for the PostHog dev stack.
//
// Usage:
//   node .agents/skills/run-posthog/driver.mjs                  # health + UI screenshot
//   node .agents/skills/run-posthog/driver.mjs --no-browser     # health checks only
//   BASE_URL=http://localhost:8010 node .../driver.mjs          # override target
//
// Exit codes: 0 = stack healthy and login renders, non-zero otherwise.
// Screenshot lands at /tmp/posthog-shots/<timestamp>.png and the latest
// is symlinked to /tmp/posthog-shots/latest.png.

import { mkdirSync, rmSync, symlinkSync } from "node:fs"
import { join } from "node:path"

const BASE_URL = process.env.BASE_URL ?? "http://localhost:8010"
const SHOTS_DIR = "/tmp/posthog-shots"
const NO_BROWSER = process.argv.includes("--no-browser")

const ok = (msg) => console.log(`\x1b[32m✓\x1b[0m ${msg}`)
class SmokeError extends Error {}
const fail = (msg) => {
    throw new SmokeError(msg)
}

async function probe(url, expectStatuses = [200]) {
    let res
    try {
        res = await fetch(url, { redirect: "manual" })
    } catch (e) {
        fail(`fetch ${url}: ${e.message}`)
    }
    if (!expectStatuses.includes(res.status)) {
        fail(`${url} returned ${res.status}, expected one of ${expectStatuses.join(",")}`)
    }
    ok(`${url} → ${res.status}`)
    return res
}

async function smokeHttp() {
    const [, , apiRes] = await Promise.all([
        probe(`${BASE_URL}/_health`),
        probe(`${BASE_URL}/`, [200, 302]),
        probe(`${BASE_URL}/api/projects/@current`, [401, 403]),
    ])
    const body = await apiRes.json().catch(() => ({}))
    if (body?.code !== "not_authenticated" && body?.type !== "authentication_error") {
        fail(`unexpected /api body: ${JSON.stringify(body).slice(0, 200)}`)
    }
    ok("API returns auth challenge (DB reachable)")
}

async function smokeBrowser() {
    mkdirSync(SHOTS_DIR, { recursive: true })

    const { chromium } = await import("playwright")
    const browser = await chromium.launch()
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } })
    const page = await ctx.newPage()
    const errors = []
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`))
    page.on("console", (m) => {
        if (m.type() === "error") errors.push(`console.error: ${m.text()}`)
    })

    // `networkidle` / `load` never settle because PostHog.js + Vite HMR keep
    // polling. Use `domcontentloaded` and wait for a `[data-attr]` element —
    // PostHog's test-id convention, present on every rendered page.
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded", timeout: 30_000 })
    await page.locator("[data-attr]").first().waitFor({ timeout: 30_000 })
    const url = page.url()
    const title = await page.title()
    ok(`navigated to ${url} (title: ${title || "<empty>"})`)

    if (!/preflight|signup|login/i.test(url)) {
        fail(`unexpected landing URL: ${url}`)
    }

    const stamp = new Date().toISOString().replace(/[:.]/g, "-")
    const shot = join(SHOTS_DIR, `${stamp}.png`)
    await page.screenshot({ path: shot })
    const latest = join(SHOTS_DIR, "latest.png")
    rmSync(latest, { force: true })
    symlinkSync(shot, latest)
    ok(`screenshot → ${shot}`)

    await browser.close()

    if (errors.length) {
        console.warn(`\x1b[33m!\x1b[0m ${errors.length} console error(s):`)
        for (const e of errors.slice(0, 10)) console.warn(`   ${e}`)
    }
}

try {
    await smokeHttp()
    if (!NO_BROWSER) await smokeBrowser()
    ok("dev stack healthy")
} catch (e) {
    if (e instanceof SmokeError) {
        console.error(`\x1b[31m✗\x1b[0m ${e.message}`)
        process.exit(1)
    }
    throw e
}
