import path from 'path'

import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Logs', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.describe('UI integration tests (mocked API)', () => {
        test.beforeEach(async ({ page, playwrightSetup }) => {
            await playwrightSetup.login(page, workspace!)

            // Mock APIs BEFORE navigation to avoid race conditions
            await page.route('**/api/environments/*/logs/query/', (route) =>
                route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    path: path.resolve(__dirname, '../../mocks/logs/logs_query_response.json'),
                })
            )

            await page.route('**/api/environments/*/logs/sparkline/', (route) =>
                route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    path: path.resolve(__dirname, '../../mocks/logs/logs_sparkline_response.json'),
                })
            )

            await page.route('**/api/environments/*/logs/values*', (route) =>
                route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    path: path.resolve(__dirname, '../../mocks/logs/logs_values_response.json'),
                })
            )

            // The facet rail populates the Level and Service facets from this endpoint, keyed by the
            // requested facetField. Return sensible values + non-zero counts for each (a fixed facet
            // value with a zero count renders disabled and can't be clicked).
            const facetValuesByField: Record<string, { value: string; count: number }[]> = {
                service_name: [
                    { value: 'api-service', count: 42 },
                    { value: 'web-frontend', count: 17 },
                ],
                severity_text: [
                    { value: 'error', count: 12 },
                    { value: 'info', count: 8 },
                ],
            }
            await page.route('**/logs/facet_values/', (route) => {
                const facetField = route.request().postDataJSON()?.query?.facetField
                const results = facetValuesByField[facetField] ?? []
                return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ results }) })
            })

            // Resource-attribute presence probe — return none so only the Level and Service column
            // facets render, keeping the rail deterministic.
            await page.route('**/logs/attributes/', (route) =>
                route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ results: [] }) })
            )

            await page.goto(`/project/${workspace!.team_id}/logs`)
            await page.waitForLoadState('networkidle')
        })

        test('service facet passes serviceNames to API', async ({ page }) => {
            // ARRANGE: Set up request interception that only captures requests with serviceNames
            // This ensures we capture the filter-triggered request, not the initial page load
            const requestPromise = page.waitForRequest((req) => {
                if (!req.url().includes('/logs/query') || req.method() !== 'POST') {
                    return false
                }
                try {
                    const body = req.postDataJSON()
                    return body?.query?.serviceNames && body.query.serviceNames.length > 0
                } catch {
                    return false
                }
            })

            // ACT: Select a value from the Service facet in the rail
            await page.locator('[data-attr="logs-facet-service-api-service"]').click()

            // Wait for the filter-triggered request
            const request = await requestPromise

            // ASSERT: Verify the request contains serviceNames
            const body = request.postDataJSON()
            expect(body.query.serviceNames).toBeDefined()
            expect(body.query.serviceNames.length).toBeGreaterThan(0)
        })

        test('level facet passes severityLevels to API', async ({ page }) => {
            // ARRANGE: Set up request interception that only captures requests with severityLevels
            // This ensures we capture the filter-triggered request, not the initial page load
            const requestPromise = page.waitForRequest((req) => {
                if (!req.url().includes('/logs/query') || req.method() !== 'POST') {
                    return false
                }
                try {
                    const body = req.postDataJSON()
                    return body?.query?.severityLevels && body.query.severityLevels.length > 0
                } catch {
                    return false
                }
            })

            // ACT: Select "Error" from the Level facet in the rail
            await page.locator('[data-attr="logs-facet-level-error"]').click()

            // Wait for the filter-triggered request
            const request = await requestPromise

            // ASSERT: Verify the request contains severityLevels with 'error'
            const body = request.postDataJSON()
            expect(body.query.severityLevels).toBeDefined()
            expect(body.query.severityLevels).toContain('error')
        })
    })

    test.describe('E2E tests', () => {
        // TODO: Add full end-to-end tests without mocked APIs
    })
})
