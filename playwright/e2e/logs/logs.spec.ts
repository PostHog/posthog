import path from 'path'

import { expect, test } from '../../utils/playwright-test-base'

test.describe('Logs', () => {
    test.describe('UI integration tests (mocked API)', () => {
        test.beforeEach(async ({ page }) => {
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

            await page.goto('/project/1/logs')
            await page.waitForLoadState('networkidle')
        })

        test('service filter passes serviceNames to API', async ({ page }) => {
            // ARRANGE: Start waiting BEFORE the action (prevents race condition)
            const [request] = await Promise.all([
                page.waitForRequest((req) => req.url().includes('/logs/query') && req.method() === 'POST'),
                // ACT: Click the service filter and select a value
                (async () => {
                    await page.getByTestId('logs-service-filter').click()
                    // Wait for dropdown to be visible, then select first option
                    await page.locator('[data-attr^="prop-val-"]').first().click()
                })(),
            ])

            // ASSERT: Verify the request contains serviceNames
            const body = request.postDataJSON()
            expect(body.query.serviceNames).toBeDefined()
            expect(body.query.serviceNames.length).toBeGreaterThan(0)
        })

        test('severity filter passes severityLevels to API', async ({ page }) => {
            // ARRANGE: Start waiting BEFORE the action (prevents race condition)
            const [request] = await Promise.all([
                page.waitForRequest((req) => req.url().includes('/logs/query') && req.method() === 'POST'),
                // ACT: Click the severity filter and select "Error"
                (async () => {
                    await page.getByTestId('logs-severity-filter').click()
                    // Select "Error" from the dropdown menu
                    await page.locator('[data-attr="logs-severity-option-error"]').click()
                    // Close the menu by pressing Escape
                    await page.keyboard.press('Escape')
                })(),
            ])

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
