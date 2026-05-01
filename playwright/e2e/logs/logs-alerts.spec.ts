import { randomString } from '../../utils'
import { mockFeatureFlags } from '../../utils/mockApi'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Logs Alerts', () => {
    const ALERTS_API = '**/api/projects/*/logs/alerts/'
    const ALERTS_API_DETAIL = '**/api/projects/*/logs/alerts/*/'
    const SPARKLINE_API = '**/api/environments/*/logs/sparkline/'

    const makeAlert = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
        id: '019d-test-alert-id',
        name: 'Test Alert',
        enabled: false,
        state: 'not_firing',
        filters: { severityLevels: ['error'], serviceNames: [] },
        threshold_count: 100,
        threshold_operator: 'above',
        window_minutes: 10,
        evaluation_periods: 1,
        datapoints_to_alarm: 1,
        cooldown_minutes: 0,
        ...overrides,
    })

    test('creates, edits, and deletes an alert via the page-based flow', async ({ page }) => {
        const alertName = randomString('alert')
        let createdAlert: Record<string, unknown> | null = null

        await test.step('mock APIs and navigate to alerts tab', async () => {
            await page.route(ALERTS_API, async (route) => {
                const method = route.request().method()
                if (method === 'GET') {
                    await route.fulfill({
                        status: 200,
                        contentType: 'application/json',
                        body: JSON.stringify({ results: createdAlert ? [createdAlert] : [] }),
                    })
                } else if (method === 'POST') {
                    const body = route.request().postDataJSON()
                    createdAlert = makeAlert({ ...body, id: '019d-created-alert-id', name: body.name })
                    await route.fulfill({
                        status: 201,
                        contentType: 'application/json',
                        body: JSON.stringify(createdAlert),
                    })
                } else {
                    await route.continue()
                }
            })

            await page.route(ALERTS_API_DETAIL, async (route) => {
                const method = route.request().method()
                if (method === 'GET') {
                    await route.fulfill({
                        status: 200,
                        contentType: 'application/json',
                        body: JSON.stringify(createdAlert ?? {}),
                    })
                } else if (method === 'PATCH') {
                    const body = route.request().postDataJSON()
                    createdAlert = { ...createdAlert, ...body }
                    await route.fulfill({
                        status: 200,
                        contentType: 'application/json',
                        body: JSON.stringify(createdAlert),
                    })
                } else if (method === 'DELETE') {
                    createdAlert = null
                    await route.fulfill({ status: 204 })
                } else {
                    await route.continue()
                }
            })

            await page.route(SPARKLINE_API, async (route) => {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify([]),
                })
            })

            // logsAlertNotificationLogic fetches hog functions on mount; mocking it prevents
            // the loadExistingHogFunctionsSuccess → loadAlert → resetAlertForm race that
            // would wipe form changes made during the test.
            await page.route(
                (url) => url.pathname.includes('/hog_functions'),
                async (route) => {
                    await route.fulfill({
                        status: 200,
                        contentType: 'application/json',
                        body: JSON.stringify({ results: [], count: 0 }),
                    })
                }
            )

            await mockFeatureFlags(page, { 'logs-tabbed-view': true, 'logs-alerting': true })

            await page.goto('/project/1/logs?activeTab=alerts')
            // loginBeforeTests navigates to the project root before our mocks are registered,
            // so posthog-js may have already cached flags. Force a reload to pick up our mock.
            await page.evaluate(() => void (window as any).posthog?.reloadFeatureFlags?.())
            await expect(page.getByText('No alerts configured yet.')).toBeVisible({ timeout: 15000 })
        })

        await test.step('navigate to the new alert page', async () => {
            await page.getByRole('link', { name: 'New alert' }).click()
            await page.waitForURL('**/logs/alerts/new')
        })

        await test.step('set name — Create draft stays disabled until a filter is added', async () => {
            await page.getByTestId('scene-name').locator('button').first().click()
            await expect(page.getByTestId('scene-title-textarea')).toBeVisible()
            await page.getByTestId('scene-title-textarea').fill(alertName)
            await page.keyboard.press('Tab')

            await expect(page.getByRole('button', { name: 'Create draft' })).toBeDisabled()
        })

        await test.step('add severity filter and create the draft', async () => {
            await page.getByTestId('logs-severity-filter').click()
            await page.locator('[data-attr="logs-severity-option-error"]').click()
            // Close the dropdown by clicking the Filters heading
            await page.getByRole('heading', { name: 'Filters' }).click()

            await expect(page.getByRole('button', { name: 'Create draft' })).toBeEnabled()
            await page.getByRole('button', { name: 'Create draft' }).click()

            await page.waitForURL('**/logs/alerts/019d-created-alert-id')
            await expect(page.getByText('Draft alert created')).toBeVisible()
        })

        await test.step('detail page shows persisted name and settings', async () => {
            await expect(page.getByTestId('scene-name')).toContainText(alertName)
            // exact: true avoids matching the "This alert is disabled — no checks are running." banner
            await expect(page.getByText('Disabled', { exact: true })).toBeVisible()
            // Wait for the form to load, then check severity persisted from creation
            await expect(page.getByTestId('logs-severity-filter')).toContainText('Error', { ignoreCase: true })
            // Threshold count persists from the creation payload (default: 100)
            await expect(page.locator('input[type="number"]').first()).toHaveValue('100')
            // Save is disabled — no changes have been made since load
            await expect(page.getByRole('button', { name: 'Save' })).toBeDisabled()
        })

        await test.step('edit threshold and save', async () => {
            // The threshold input is the first number spinbutton in the form (Rules section)
            const thresholdInput = page.locator('input[type="number"]').first()
            await thresholdInput.fill('50')
            await page.keyboard.press('Tab')

            const saveButton = page.getByRole('button', { name: 'Save' })
            await expect(saveButton).toBeEnabled()
            await saveButton.click()

            await expect(page.getByText('Alert updated')).toBeVisible()
            // Wait for the form to reload before proceeding to delete
            await expect(saveButton).toBeDisabled()
        })

        await test.step('delete the alert', async () => {
            await page.locator('[aria-label="more"]').click()
            await page.getByRole('menuitem', { name: 'Delete' }).click()

            await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()

            await expect(page.getByText('Alert deleted')).toBeVisible()
            // Verify navigation back to the alerts list
            await page.waitForURL(/logs.*activeTab=alerts/)
        })
    })
})
