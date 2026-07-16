import { randomString } from '../utils'
import { expect, test } from '../utils/workspace-test-base'

// Capture and flags are served by separate Rust services fronted by the Caddy dev proxy,
// not by the Django server Playwright's baseURL points at.
const PROXY_BASE_URL = process.env.E2E_PROXY_URL || 'http://localhost:8010'

test.describe('Event ingestion', () => {
    test('an event sent to the real capture endpoint becomes queryable', async ({ request, playwrightSetup }) => {
        test.setTimeout(120_000)
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        const eventName = randomString('e2e_ingestion_')
        const authHeaders = { Authorization: `Bearer ${workspace.personal_api_key}` }
        let apiToken = ''

        await test.step('fetch the team api token', async () => {
            const team = await request.get(`/api/environments/${workspace.team_id}/`, { headers: authHeaders })
            expect(team.ok()).toBe(true)
            apiToken = (await team.json()).api_token
        })

        await test.step('send an event through the capture endpoint', async () => {
            const captured = await request.post(`${PROXY_BASE_URL}/e/`, {
                data: {
                    api_key: apiToken,
                    event: eventName,
                    distinct_id: randomString('e2e-user-'),
                    timestamp: new Date().toISOString(),
                },
            })
            expect(captured.ok()).toBe(true)
        })

        await test.step('poll until the event has been ingested and is queryable', async () => {
            await expect
                .poll(
                    async () => {
                        const resp = await request.post(`/api/environments/${workspace.team_id}/query/`, {
                            headers: authHeaders,
                            data: {
                                query: {
                                    kind: 'HogQLQuery',
                                    query: `SELECT count() FROM events WHERE event = '${eventName}'`,
                                },
                            },
                        })
                        const body = await resp.json()
                        return Number(body.results?.[0]?.[0] ?? 0)
                    },
                    { timeout: 90_000, intervals: [2_000, 5_000] }
                )
                .toBeGreaterThan(0)
        })
    })
})
