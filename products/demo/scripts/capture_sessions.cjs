const { createRequire } = require('node:module')
const path = require('node:path')
const { parseArgs } = require('node:util')

function loopbackUrl(value, name) {
    const url = new URL(value)
    if (
        !['http:', 'https:'].includes(url.protocol) ||
        !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) ||
        url.username ||
        url.password ||
        url.pathname !== '/' ||
        url.search ||
        url.hash
    ) {
        throw new Error(`${name} must be a loopback HTTP origin, such as http://localhost:8010`)
    }
    return url
}

function snapshotPayload(request, sessionId) {
    const body = request.postData()
    if (!body) {
        return false
    }
    try {
        let data
        try {
            data = JSON.parse(body)
        } catch {
            const encoded = new URLSearchParams(body).get('data')
            try {
                data = JSON.parse(encoded)
            } catch {
                data = JSON.parse(Buffer.from(encoded || '', 'base64').toString('utf8'))
            }
        }
        const events = Array.isArray(data) ? data : data.batch || [data]
        return events.some(
            (event) =>
                event.event === '$snapshot' &&
                event.properties?.$session_id === sessionId &&
                event.properties?.$snapshot_data?.length > 0
        )
    } catch {
        return false
    }
}

async function main() {
    const { values } = parseArgs({
        options: {
            'app-url': { type: 'string', default: 'http://localhost:3000' },
            sessions: { type: 'string', default: '3' },
            help: { type: 'boolean', default: false },
        },
    })
    if (values.help) {
        console.info(
            'NEXT_PUBLIC_POSTHOG_KEY=<project token> NEXT_PUBLIC_POSTHOG_HOST=http://localhost:8010 ' +
                'node products/demo/scripts/capture_sessions.cjs --app-url http://localhost:3000 --sessions 3\n' +
                'Run the Hedgebox dummy app with the same key and host first.\n' +
                'The output reports snapshot acceptance; check Sessions for ingestion and playback.'
        )
        return
    }
    const appUrl = loopbackUrl(values['app-url'], '--app-url')
    const posthogHost = loopbackUrl(process.env.NEXT_PUBLIC_POSTHOG_HOST || '', 'NEXT_PUBLIC_POSTHOG_HOST')
    const projectToken = process.env.NEXT_PUBLIC_POSTHOG_KEY
    if (!projectToken) {
        throw new Error('Set NEXT_PUBLIC_POSTHOG_KEY to the selected local project token')
    }
    const sessionCount = Number(values.sessions)
    if (!Number.isInteger(sessionCount) || sessionCount < 1 || sessionCount > 10) {
        throw new Error('--sessions must be an integer from 1 to 10')
    }

    const dummyRequire = createRequire(path.resolve(__dirname, '../../../tools/hedgebox-dummy/package.json'))
    const { chromium } = dummyRequire('playwright')
    const browser = await chromium.launch()
    try {
        for (let index = 0; index < sessionCount; index++) {
            const context = await browser.newContext({ viewport: { width: 1280, height: 800 } })
            try {
                await context.route('**/*', (route) => {
                    const url = new URL(route.request().url())
                    return [appUrl.origin, posthogHost.origin].includes(url.origin) ? route.continue() : route.abort()
                })
                const page = await context.newPage()
                page.setDefaultTimeout(30_000)
                await page.goto(new URL('/login', appUrl).href)
                await page.waitForFunction(() => window.posthog?.__loaded)
                const correctProject = await page.evaluate(
                    ({ token, host }) =>
                        window.posthog.get_config('token') === token &&
                        new URL(window.posthog.get_config('api_host')).origin === host,
                    { token: projectToken, host: posthogHost.origin }
                )
                if (!correctProject) {
                    throw new Error(
                        'The dummy app uses a different project token or host. Restart it with the selected values'
                    )
                }
                await page.waitForFunction(() => window.posthog.sessionRecordingStarted())
                const sessionId = await page.evaluate(() => window.posthog.get_session_id())
                await page.locator('input[name="email"]').fill(`replay-demo-${index + 1}@example.com`)
                await page.locator('input[name="password"]').fill('local-demo-only')
                await page.locator('button[type="submit"]').click()
                await page.waitForURL('**/files')
                const upload = page.getByRole('button', { name: 'Upload file', exact: false })
                await upload.click()
                await upload.waitFor({ state: 'visible' })
                await page.mouse.move(400, 350)
                await page.mouse.wheel(0, 400)

                const snapshotResponse = await page.waitForResponse(
                    (response) =>
                        new URL(response.url()).origin === posthogHost.origin &&
                        new URL(response.url()).pathname === '/s/' &&
                        response.ok() &&
                        snapshotPayload(response.request(), sessionId),
                    { timeout: 30_000 }
                )
                await snapshotResponse.finished()
                console.info(JSON.stringify({ session_id: sessionId, status: 'snapshots_accepted_pending_ingestion' }))
            } finally {
                await context.close()
            }
        }
    } finally {
        await browser.close()
    }
}

main().catch((error) => {
    console.error(
        `Session capture failed: ${error.message.replaceAll(process.env.NEXT_PUBLIC_POSTHOG_KEY || '\0', '[redacted]')}`
    )
    process.exitCode = 1
})
