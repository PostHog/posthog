import { randomString } from '../utils'
import { expect, test } from '../utils/workspace-test-base'

// The flags service is a separate Rust service fronted by the Caddy dev proxy,
// not the Django server Playwright's baseURL points at.
const PROXY_BASE_URL = process.env.E2E_PROXY_URL || 'http://localhost:8010'

test.describe('Feature flags', () => {
    test('a flag created in the UI is evaluated by the flags endpoint', async ({ page, request, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.login(page, workspace)
        const flagKey = randomString('e2e-flag-')

        await test.step('create a 100% rollout flag via the UI', async () => {
            await page.goto('/feature_flags')
            await page.locator('[data-attr="new-feature-flag"]').click()
            await page.locator('[data-attr="blank-feature-flag-template"]').click()
            await page.locator('[data-attr="feature-flag-key"]').fill(flagKey)
            await page.locator('[data-attr="rollout-percentage"]').fill('100')
            const saveButton = page.locator('[data-attr="save-feature-flag"]').first()
            await expect(saveButton).toBeEnabled()
            await saveButton.click()
            await page.waitForURL(/\/feature_flags\/\d+/)
        })

        await test.step('the flags endpoint evaluates the flag as enabled', async () => {
            const team = await page.request.get(`/api/environments/${workspace.team_id}/`)
            const apiToken = (await team.json()).api_token

            await expect
                .poll(
                    async () => {
                        const resp = await request.post(`${PROXY_BASE_URL}/flags`, {
                            data: { api_key: apiToken, distinct_id: 'e2e-flag-user' },
                        })
                        const body = await resp
                            .json()
                            .catch(() => ({ error: `non-JSON response, status ${resp.status()}` }))
                        return body.flags?.[flagKey]?.enabled ?? false
                    },
                    { timeout: 30_000, intervals: [1_000, 2_000] }
                )
                .toBe(true)
        })
    })
})
