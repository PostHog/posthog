import process from 'node:process'
import { chromium } from 'playwright'

const AUTH_REQUIRED_EXIT = 2
const DEFAULT_LOGIN_TIMEOUT_SECONDS = 600
const SESSION_COOKIE_NAME = 'sessionid'
const CSRF_COOKIE_NAME = 'posthog_csrftoken'

const [mode, host, profilePath, rawTimeoutSeconds] = process.argv.slice(2)
const timeoutSeconds = Number(rawTimeoutSeconds || DEFAULT_LOGIN_TIMEOUT_SECONDS)

if (!['cookies', 'login'].includes(mode) || !host || !profilePath || !Number.isFinite(timeoutSeconds)) {
    process.exit(1)
}

const context = await chromium.launchPersistentContext(profilePath, {
    channel: 'chrome',
    headless: mode === 'cookies',
})

const page = context.pages()[0] ?? (await context.newPage())

async function isAuthenticated() {
    try {
        const response = await context.request.get(`${host}/api/users/@me/`)
        return response.ok()
    } catch {
        return false
    }
}

async function waitForAuthentication() {
    const deadline = Date.now() + timeoutSeconds * 1000
    while (Date.now() < deadline) {
        if (await isAuthenticated()) {
            return true
        }
        await page.waitForTimeout(1000)
    }
    return false
}

async function credentials() {
    const cookies = await context.cookies(host)
    const session = cookies.find((cookie) => cookie.name === SESSION_COOKIE_NAME)?.value
    const csrf = cookies.find((cookie) => cookie.name === CSRF_COOKIE_NAME)?.value
    if (!session || !csrf) {
        return null
    }
    return { session_id: session, csrf_token: csrf }
}

try {
    await page.goto(host, { waitUntil: 'domcontentloaded' })
    const authenticated = mode === 'login' ? await waitForAuthentication() : await isAuthenticated()
    const browserCredentials = authenticated ? await credentials() : null
    if (!browserCredentials) {
        process.exitCode = AUTH_REQUIRED_EXIT
    } else {
        process.stdout.write(JSON.stringify(browserCredentials))
    }
} finally {
    await context.close()
}
