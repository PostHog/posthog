// Product-owned specs reach Playwright helpers through this alias, not a relative path
// (see products/replay/frontend/e2e/player.spec.ts).
import { expect, test } from '@playwright-utils/workspace-test-base'
import fs from 'fs'
import path from 'path'

// Capture is served by a separate Rust service behind the Caddy dev proxy, not by the
// Django server Playwright's baseURL points at. Mirrors playwright/e2e/ingestion-capture.spec.ts.
const PROXY_BASE_URL = process.env.E2E_PROXY_URL || 'http://localhost:8010'

// PAIRED TEST: common/ingestion/acceptance_tests/test_ai_multimodal_blessed_path.py asserts the
// image is offloaded to a blob pointer in ClickHouse. Neither test alone is end-to-end coverage:
// that one stops at the data layer, this one starts from a seeded event. If you change the fixture
// or the assertions here, update that test too or the E2E property is silently lost.
const FIXTURE = JSON.parse(
    fs.readFileSync(path.join(__dirname, '../../../../common/fixtures/ai-multimodal/generation-event.json'), 'utf-8')
)

test.describe('AI observability multimodal trace', () => {
    test('a screenshot sent through ingestion renders in the trace view', async ({
        page,
        request,
        playwrightSetup,
    }) => {
        test.setTimeout(180_000)
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        const authHeaders = { Authorization: `Bearer ${workspace.personal_api_key}` }

        // Unique per run so concurrent and repeat runs cannot assert against each other's rows.
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
            await expect
                .poll(
                    async () => {
                        const resp = await request.post(`/api/environments/${workspace.team_id}/query/`, {
                            headers: authHeaders,
                            data: {
                                // Without this the endpoint serves a cached result for up to 5 minutes,
                                // so the first poll's empty result would be replayed for the rest of the window.
                                refresh: 'force_blocking',
                                query: {
                                    kind: 'HogQLQuery',
                                    query: `SELECT input FROM posthog.ai_events WHERE trace_id = '${traceId}' LIMIT 1`,
                                },
                            },
                        })
                        // A 4xx other than rate limiting means the query itself is bad — waiting won't fix it.
                        if (resp.status() >= 400 && resp.status() < 500 && resp.status() !== 429) {
                            throw new Error(`query endpoint returned ${resp.status()}: ${await resp.text()}`)
                        }
                        const body = await resp.json()
                        return String(body.results?.[0]?.[0] ?? '')
                    },
                    { timeout: 120_000, intervals: [2_000, 5_000] }
                )
                .toContain('phaiblob://')
        })

        await test.step('open the trace and assert the image decoded', async () => {
            await page.goto(`/ai-observability/traces/${traceId}`)

            const image = page.locator('[data-attr="ai-message-image"]').first()
            await expect(image).toBeVisible()

            // A decode check, not a pixel diff: this catches a truncated or corrupt payload
            // precisely, exercises the pointer -> ai_blob API read path, and cannot flake on
            // rendering differences. Visual regressions belong in Storybook (playwright/README.md:57).
            await expect
                .poll(async () => await image.evaluate((img: HTMLImageElement) => img.naturalWidth), {
                    timeout: 30_000,
                    intervals: [500, 1_000],
                })
                .toBeGreaterThan(0)
        })
    })
})
