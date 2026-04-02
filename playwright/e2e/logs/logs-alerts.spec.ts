import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Logs Alerts CRUD', () => {
    const ALERTS_API = '**/api/projects/*/logs/alerts/'
    const ALERTS_API_DETAIL = '**/api/projects/*/logs/alerts/*/'

    const makeAlert = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
        id: '019d-test-alert-id',
        name: 'Test Alert',
        enabled: true,
        state: 'not_firing',
        filters: { severityLevels: ['error'], serviceNames: ['api-gateway'] },
        threshold_count: 50,
        threshold_operator: 'above',
        window_minutes: 10,
        evaluation_periods: 1,
        datapoints_to_alarm: 1,
        cooldown_minutes: 0,
        ...overrides,
    })

    // The kea-forms <Form> renders as <form class="LemonModal__layout">
    const formModal = 'form.LemonModal__layout'

    test('creates an alert, verifies edit populates persisted values, edits, and deletes', async ({ page }) => {
        const alertName = randomString('alert')
        let createdAlert: Record<string, unknown> | null = null

        await test.step('mock APIs and navigate to alerts', async () => {
            // Mock the alerts list and create endpoints
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
                    createdAlert = makeAlert({
                        ...body,
                        id: '019d-created-alert-id',
                        name: body.name,
                    })
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
                if (method === 'PATCH') {
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
                } else if (method === 'GET') {
                    if (!createdAlert) {
                        await route.fulfill({ status: 404 })
                        return
                    }
                    await route.fulfill({
                        status: 200,
                        contentType: 'application/json',
                        body: JSON.stringify(createdAlert),
                    })
                } else {
                    await route.continue()
                }
            })

            // Inject the logs-alerting feature flag before the app hydrates.
            // The settings map gates the Alerting section behind this flag.
            await page.addInitScript(() => {
                let _context: any
                Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
                    get() {
                        return _context
                    },
                    set(value: any) {
                        if (value) {
                            value.persisted_feature_flags = [
                                ...(value.persisted_feature_flags || []),
                                'logs-settings',
                                'logs-alerting',
                            ]
                        }
                        _context = value
                    },
                    configurable: true,
                })
            })

            await page.goto('/project/1/settings/environment-logs')
            await expect(page.getByRole('heading', { name: 'Alerting' })).toBeVisible({ timeout: 15000 })
            // Wait for the mocked empty alerts list to render
            await expect(page.getByText('No alerts configured yet.')).toBeVisible()
        })

        await test.step('create an alert with severity filter', async () => {
            await page.getByRole('button', { name: 'New alert' }).click()
            await expect(page.locator(formModal)).toBeVisible()

            // Fill in name
            await page.locator(formModal).getByPlaceholder('e.g. API 5xx errors').fill(alertName)

            // Select severity — panels are already expanded via defaultActiveKeys
            await page.locator(formModal).getByTestId('logs-severity-filter').click()
            await page.locator('[data-attr="logs-severity-option-error"]').click()
            // Close dropdown by clicking elsewhere in the modal, not Escape (which closes the modal)
            await page.locator(formModal).getByPlaceholder('e.g. API 5xx errors').click()

            // Submit the form
            await page.locator(formModal).getByRole('button', { name: 'Create alert' }).click()

            // Assert modal closes and success toast
            await expect(page.locator(formModal)).not.toBeVisible()
            await expect(page.getByText('Alert created')).toBeVisible()
        })

        await test.step('verify alert appears in list', async () => {
            await expect(page.getByRole('button', { name: alertName })).toBeVisible()
        })

        await test.step('edit modal populates persisted values', async () => {
            await page.getByRole('button', { name: alertName }).click()
            await expect(page.locator(formModal)).toBeVisible()
            await expect(page.getByRole('heading', { name: 'Edit alert' })).toBeVisible()

            // Verify name is populated
            await expect(page.locator(formModal).getByPlaceholder('e.g. API 5xx errors')).toHaveValue(alertName)

            // Verify severity filter shows "Error" (not "All levels")
            await expect(page.locator(formModal).getByTestId('logs-severity-filter')).toContainText('error', {
                ignoreCase: true,
            })

            // Verify save button is disabled (no changes)
            await expect(page.locator(formModal).getByRole('button', { name: 'Save' })).toBeDisabled()
        })

        await test.step('edit the alert name and save', async () => {
            const updatedName = alertName + '-updated'
            await page.locator(formModal).getByPlaceholder('e.g. API 5xx errors').fill(updatedName)

            // Save button should now be enabled
            const saveButton = page.locator(formModal).getByRole('button', { name: 'Save' })
            await expect(saveButton).toBeEnabled()
            await saveButton.click()

            // Assert modal closes and success toast
            await expect(page.locator(formModal)).not.toBeVisible()
            await expect(page.getByText('Alert updated')).toBeVisible()

            // Verify updated name in list
            await expect(page.getByRole('button', { name: updatedName })).toBeVisible()
        })

        await test.step('delete the alert', async () => {
            await page.locator('[aria-label="more"]').click()
            await page.getByRole('menuitem', { name: 'Delete' }).click()

            // Confirm in the deletion dialog
            await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click()

            // Assert success
            await expect(page.getByText('Alert deleted')).toBeVisible()
            await expect(page.getByText('No alerts configured yet.')).toBeVisible()
        })
    })
})
