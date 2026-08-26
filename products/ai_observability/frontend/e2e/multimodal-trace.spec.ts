import { expect, test } from '@playwright-utils/workspace-test-base'
import crypto from 'crypto'
import fs from 'fs'
import path from 'path'

// Capture runs as a separate Rust service behind the Caddy dev proxy, not on the Django
// server that Playwright's baseURL points at.
const PROXY_BASE_URL = process.env.E2E_PROXY_URL || 'http://localhost:8010'

// Paired with common/ingestion/acceptance_tests/test_ai_multimodal_blessed_path.py, which covers
// ingestion. Only the two together are end-to-end, so changes to the fixture or the assertions
// here need the matching change there.
const FIXTURE_DIR = path.join(__dirname, '../../../../common/fixtures/ai-multimodal')
const FIXTURE = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, 'generation-event.json'), 'utf-8'))
const SCREENSHOT_BYTES = fs.readFileSync(path.join(FIXTURE_DIR, 'screenshot.png'))
const POINTER_RE = /phaiblob:\/\/v1\/sha256\/(?<hash>[0-9a-f]{64})\?mime=(?<mime>[^&]+)&size=(?<size>\d+)/

test.describe('AI observability multimodal trace', () => {
    test('a screenshot sent through ingestion renders in the trace view', async ({
        page,
        request,
        playwrightSetup,
    }) => {
        test.setTimeout(180_000)
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        const authHeaders = { Authorization: `Bearer ${workspace.personal_api_key}` }

        const traceId = `e2e-multimodal-${Date.now()}-${Math.random().toString(36).slice(2)}`
        const distinctId = `e2e-multimodal-user-${traceId}`
        let apiToken = ''

        await test.step('fetch the team api token', async () => {
            const team = await request.get(`/api/environments/${workspace.team_id}/`, { headers: authHeaders })
            expect(team.ok()).toBe(true)
            apiToken = (await team.json()).api_token
        })

        await test.step('send the recorded event through the real AI capture lane', async () => {
            const captured = await request.post(`${PROXY_BASE_URL}/i/v0/ai/batch/`, {
                data: {
                    api_key: apiToken,
                    batch: [
                        {
                            event: FIXTURE.event,
                            distinct_id: distinctId,
                            timestamp: new Date().toISOString(),
                            properties: { ...FIXTURE.properties, $ai_trace_id: traceId },
                        },
                    ],
                },
            })
            expect(captured.ok()).toBe(true)
        })

        await test.step('poll until ingestion has offloaded the image and stored a pointer', async () => {
            let storedInput = ''

            await expect
                .poll(
                    async () => {
                        const resp = await request.post(`/api/environments/${workspace.team_id}/query/`, {
                            headers: authHeaders,
                            data: {
                                // Without this the endpoint caches for 5 minutes, so every later poll
                                // replays the first one's empty result.
                                refresh: 'force_blocking',
                                query: {
                                    kind: 'HogQLQuery',
                                    query: `SELECT input FROM posthog.ai_events WHERE trace_id = '${traceId}' LIMIT 1`,
                                },
                            },
                        })
                        // A 4xx other than rate limiting means the query itself is bad, so polling on
                        // would just burn the timeout.
                        if (resp.status() >= 400 && resp.status() < 500 && resp.status() !== 429) {
                            throw new Error(`query endpoint returned ${resp.status()}: ${await resp.text()}`)
                        }
                        const body = await resp.json()
                        storedInput = String(body.results?.[0]?.[0] ?? '')
                        return storedInput
                    },
                    { timeout: 120_000, intervals: [2_000, 5_000] }
                )
                .toContain('phaiblob://')

            const match = storedInput.match(POINTER_RE)
            expect(match).not.toBeNull()
            expect(match?.groups?.hash).toBe(crypto.createHash('sha256').update(SCREENSHOT_BYTES).digest('hex'))
            expect(decodeURIComponent(match?.groups?.mime ?? '')).toBe('image/png')
            expect(Number(match?.groups?.size)).toBe(SCREENSHOT_BYTES.length)
        })

        await test.step('open the trace and assert the image decoded', async () => {
            // createWorkspace is API-only and leaves `page` without session cookies, which the
            // trace view needs.
            await playwrightSetup.login(page, workspace)
            await page.goto(`/ai-observability/traces/${traceId}`)

            const image = page.locator('[data-attr="ai-message-image"]').first()
            await expect(image).toBeVisible()

            // naturalWidth is only non-zero once the browser decoded the bytes, so this proves the
            // ai_blob read path returned an intact image without flaking on rendering differences.
            await expect
                .poll(async () => await image.evaluate((img: HTMLImageElement) => img.naturalWidth), {
                    timeout: 30_000,
                    intervals: [500, 1_000],
                })
                .toBeGreaterThan(0)
        })
    })
})
