#!/usr/bin/env node
// Smoke driver for the PostHog dev stack.
//
// Usage:
//   node .claude/skills/run-posthog/driver.mjs                  # health + preflight screenshot
//   node .claude/skills/run-posthog/driver.mjs --no-browser     # HTTP probes only
//   node .claude/skills/run-posthog/driver.mjs --login          # auth + screenshot project root
//   node .claude/skills/run-posthog/driver.mjs --login --path=/insights
//   BASE_URL=http://localhost:8010 node ...                     # override target
//
// Exit codes: 0 = stack healthy and target page renders, non-zero otherwise.
// Screenshots land in /tmp/posthog-shots; auth state is cached in the same dir.

import { existsSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { join } from "node:path"

const BASE_URL = process.env.BASE_URL ?? "http://localhost:8010"
const SHOTS_DIR = "/tmp/posthog-shots"
const AUTH_FILE = join(SHOTS_DIR, "auth.json")
const STORAGE_STATE = join(SHOTS_DIR, "storage-state.json")
const NO_BROWSER = process.argv.includes("--no-browser")
const LOGIN = process.argv.includes("--login")
const PATH_ARG = process.argv.find((a) => a.startsWith("--path="))?.slice("--path=".length)

const ok = (msg) => console.log(`\x1b[32m✓\x1b[0m ${msg}`)
const warn = (msg) => console.warn(`\x1b[33m!\x1b[0m ${msg}`)
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

// Bootstrap: try cached creds first, then live signup. Returns {email, password, team_id}.
// Mirrors the playwright suite intent (one workspace per agent, reused across runs).
async function bootstrapAuth() {
    // `12345678` (the test-suite password) fails Django's password validator on
    // /api/signup/ — that path is bypassed only by management commands. Default
    // to a 3-word phrase that passes the validator and is stable across runs.
    const password = process.env.POSTHOG_DEV_PASSWORD ?? "correct-horse-battery"
    const email = process.env.POSTHOG_DEV_EMAIL ?? "test@posthog.com"

    if (existsSync(AUTH_FILE)) {
        const cached = JSON.parse(readFileSync(AUTH_FILE, "utf8"))
        if (cached.email && cached.password && cached.team_id) {
            ok(`using cached creds (${cached.email}, team ${cached.team_id})`)
            return cached
        }
    }

    // First signup attempt. On duplicate-email (user from a prior run), assume the
    // cached password matches and short-circuit to a login probe in the browser.
    const res = await fetch(`${BASE_URL}/api/signup/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            email,
            password,
            first_name: "Agent",
            organization_name: "Agent Smoke",
        }),
        redirect: "manual",
    })
    const body = await res.json().catch(() => ({}))
    let teamId = null
    if (res.status === 201) {
        // /api/signup/ doesn't return team_id directly; replay the Set-Cookie session
        // header against /api/users/@me/ to resolve it.
        teamId = await currentTeamId(res.headers.getSetCookie?.() ?? [])
        if (!teamId) fail("signup succeeded but couldn't resolve team_id")
        ok(`signed up ${email} (team ${teamId})`)
    } else if (res.status === 400 && body?.code === "unique" && body?.attr === "email") {
        warn(`${email} already exists — trusting password env/default (will fail loud if wrong)`)
    } else {
        fail(`signup failed (${res.status}): ${JSON.stringify(body).slice(0, 240)}`)
    }

    const creds = { email, password, team_id: teamId }
    mkdirSync(SHOTS_DIR, { recursive: true })
    writeFileSync(AUTH_FILE, JSON.stringify(creds, null, 2))
    return creds
}

// Resolve current team_id from a session by replaying Set-Cookie headers
// against /api/users/@me/. Used right after signup to discover the team_id
// without trusting the signup response shape.
async function currentTeamId(setCookieHeaders) {
    const cookies = setCookieHeaders.map((c) => c.split(";")[0]).join("; ")
    if (!cookies) return null
    const me = await fetch(`${BASE_URL}/api/users/@me/`, { headers: { Cookie: cookies } })
    if (!me.ok) return null
    const body = await me.json().catch(() => null)
    return body?.team?.id ?? null
}

async function smokeBrowser() {
    mkdirSync(SHOTS_DIR, { recursive: true })
    const { chromium } = await import("playwright")
    const browser = await chromium.launch()

    const ctxOpts = { viewport: { width: 1280, height: 800 } }
    if (LOGIN && existsSync(STORAGE_STATE)) ctxOpts.storageState = STORAGE_STATE
    const ctx = await browser.newContext(ctxOpts)
    const page = await ctx.newPage()
    const errors = []
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`))
    page.on("console", (m) => {
        if (m.type() === "error") errors.push(`console.error: ${m.text()}`)
    })

    let url, title
    if (LOGIN) {
        const creds = await bootstrapAuth()
        const teamId = await loginInBrowser(page, ctx, creds)
        if (!teamId) fail("logged in but couldn't resolve team_id from /api/users/@me/")
        // Persist team_id for subsequent runs that took the cached-password path.
        writeFileSync(AUTH_FILE, JSON.stringify({ ...creds, team_id: teamId }, null, 2))
        await ctx.storageState({ path: STORAGE_STATE })

        const target = PATH_ARG
            ? PATH_ARG.startsWith("/project/")
                ? PATH_ARG
                : `/project/${teamId}${PATH_ARG.startsWith("/") ? PATH_ARG : `/${PATH_ARG}`}`
            : `/project/${teamId}`
        await page.goto(`${BASE_URL}${target}`, { waitUntil: "domcontentloaded", timeout: 30_000 })
        await page.locator("[data-attr]").first().waitFor({ timeout: 30_000 })
        url = page.url()
        title = await page.title()
        ok(`navigated to ${url} (title: ${title || "<empty>"})`)
        if (/preflight|\/login|\/signup/i.test(url)) {
            fail(`expected authenticated scene at ${target}, landed on ${url}`)
        }
    } else {
        // Anonymous smoke — same as before.
        await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded", timeout: 30_000 })
        await page.locator("[data-attr]").first().waitFor({ timeout: 30_000 })
        url = page.url()
        title = await page.title()
        ok(`navigated to ${url} (title: ${title || "<empty>"})`)
        if (!/preflight|signup|login/i.test(url)) {
            fail(`unexpected landing URL: ${url}`)
        }
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
        warn(`${errors.length} console error(s):`)
        for (const e of errors.slice(0, 10)) console.warn(`   ${e}`)
    }
}

// Login from inside the browser. Mirrors playwright/utils/playwright-setup.ts:282-291 —
// `page.evaluate(fetch('/api/login/'))` runs in-page so cookies + CSRF flow automatically.
async function loginInBrowser(page, ctx, { email, password }) {
    // If a cached storageState was loaded, check whether we're still authenticated.
    // Django's session cookie is `sessionid`; `posthog_csrftoken` is the CSRF pair.
    if ((await ctx.storageState()).cookies.some((c) => c.name === "sessionid")) {
        const me = await page.request.get(`${BASE_URL}/api/users/@me/`)
        if (me.ok()) {
            const data = await me.json()
            ok(`reused cached session (${data.email}, team ${data.team.id})`)
            return data.team.id
        }
    }
    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" })
    const status = await page.evaluate(
        async ({ email, password }) => {
            const r = await fetch("/api/login/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password }),
            })
            return r.status
        },
        { email, password }
    )
    if (status !== 200) fail(`/api/login/ in-page POST returned ${status}`)
    const me = await page.request.get(`${BASE_URL}/api/users/@me/`)
    if (!me.ok()) fail(`/api/users/@me/ after login: ${me.status()}`)
    const data = await me.json()
    ok(`logged in (${data.email}, team ${data.team.id})`)
    return data.team.id
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
