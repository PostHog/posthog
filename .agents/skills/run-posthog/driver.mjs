#!/usr/bin/env node
// Smoke driver for the PostHog dev stack.
//
// Usage:
//   node .agents/skills/run-posthog/driver.mjs                  # health + UI screenshot
//   node .agents/skills/run-posthog/driver.mjs --no-browser     # health checks only
//   PROXY_URL=http://localhost:8010 node .../driver.mjs         # override target
//
// Exit codes: 0 = stack healthy and login renders, non-zero otherwise.
// Screenshot lands at /tmp/posthog-shots/<timestamp>.png and the latest
// is symlinked to /tmp/posthog-shots/latest.png.

import { existsSync, mkdirSync, symlinkSync, unlinkSync } from "node:fs"
import { join } from "node:path"

const PROXY_URL = process.env.PROXY_URL ?? "http://localhost:8010"
const DJANGO_URL = process.env.DJANGO_URL ?? "http://localhost:8000"
const SHOTS_DIR = "/tmp/posthog-shots"
const NO_BROWSER = process.argv.includes("--no-browser")

const ok = (msg) => console.log(`\x1b[32m✓\x1b[0m ${msg}`)
const fail = (msg) => {
    console.error(`\x1b[31m✗\x1b[0m ${msg}`)
    process.exit(1)
}

async function probe(url, expectStatuses = [200]) {
    const res = await fetch(url, { redirect: "manual" }).catch((e) => {
        fail(`fetch ${url}: ${e.message}`)
    })
    if (!expectStatuses.includes(res.status)) {
        fail(`${url} returned ${res.status}, expected one of ${expectStatuses.join(",")}`)
    }
    ok(`${url} → ${res.status}`)
    return res
}

async function smokeHttp() {
    await probe(`${DJANGO_URL}/_health`)
    await probe(`${PROXY_URL}/_health`)
    await probe(`${PROXY_URL}/`, [200, 302])
    const apiRes = await probe(`${PROXY_URL}/api/projects/@current`, [401, 403])
    const body = await apiRes.json().catch(() => ({}))
    if (body?.code !== "not_authenticated" && body?.type !== "authentication_error") {
        fail(`unexpected /api body: ${JSON.stringify(body).slice(0, 200)}`)
    }
    ok("API returns auth challenge (DB reachable)")
}

async function smokeBrowser() {
    if (!existsSync(SHOTS_DIR)) mkdirSync(SHOTS_DIR, { recursive: true })

    const { chromium } = await import("playwright")
    const browser = await chromium.launch()
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } })
    const page = await ctx.newPage()
    const errors = []
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`))
    page.on("console", (m) => {
        if (m.type() === "error") errors.push(`console.error: ${m.text()}`)
    })

    await page.goto(`${PROXY_URL}/`, { waitUntil: "networkidle", timeout: 60_000 })
    const url = page.url()
    const title = await page.title()
    ok(`navigated to ${url} (title: ${title || "<empty>"})`)

    if (!/preflight|signup|login/i.test(url)) {
        fail(`unexpected landing URL: ${url}`)
    }

    const stamp = new Date().toISOString().replace(/[:.]/g, "-")
    const shot = join(SHOTS_DIR, `${stamp}.png`)
    await page.screenshot({ path: shot, fullPage: true })
    const latest = join(SHOTS_DIR, "latest.png")
    if (existsSync(latest)) unlinkSync(latest)
    symlinkSync(shot, latest)
    ok(`screenshot → ${shot}`)

    await browser.close()

    if (errors.length) {
        console.warn(`\x1b[33m!\x1b[0m ${errors.length} console error(s):`)
        for (const e of errors.slice(0, 10)) console.warn(`   ${e}`)
    }
}

await smokeHttp()
if (!NO_BROWSER) await smokeBrowser()
ok("dev stack healthy")
