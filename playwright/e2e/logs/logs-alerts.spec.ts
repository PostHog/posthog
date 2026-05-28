import { Page } from '@playwright/test'

import { mockFeatureFlags } from '../../utils/mockApi'
import { expect, test } from '../../utils/playwright-test-base'

const MOCK_ALERT_ID = '019d-mock-alert-id'

type MockAlert = Record<string, unknown>

const baseAlert = (overrides: MockAlert = {}): MockAlert => ({
    id: MOCK_ALERT_ID,
    name: 'Untitled alert',
    enabled: false,
    state: 'not_firing',
    filters: {},
    threshold_count: 100,
    threshold_operator: 'above',
    window_minutes: 5,
    check_interval_minutes: 5,
    evaluation_periods: 1,
    datapoints_to_alarm: 1,
    cooldown_minutes: 0,
    snooze_until: null,
    next_check_at: null,
    last_notified_at: null,
    last_checked_at: null,
    consecutive_failures: 0,
    last_error_message: null,
    state_timeline: [],
    destination_types: [],
    first_enabled_at: null,
    created_at: '2026-04-29T00:00:00Z',
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'user-1', first_name: 'Test', email: 'test@posthog.com' },
    updated_at: null,
    ...overrides,
})

async function setupAlertMocks(
    page: Page,
    initial: MockAlert = baseAlert()
): Promise<{ alert: { current: MockAlert } }> {
    const handle = { current: { ...initial } }

    await page.route(
        (url) => /\/api\/projects\/[^/]+\/logs\/alerts\/?$/.test(url.pathname),
        async (route) => {
            const method = route.request().method()
            if (method === 'GET') {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify({ results: [handle.current], count: 1, next: null, previous: null }),
                })
            } else if (method === 'POST') {
                handle.current = baseAlert()
                await route.fulfill({
                    status: 201,
                    contentType: 'application/json',
                    body: JSON.stringify(handle.current),
                })
            } else {
                await route.continue()
            }
        }
    )

    await page.route(
        (url) => /\/api\/projects\/[^/]+\/logs\/alerts\/[^/]+\/?$/.test(url.pathname),
        async (route) => {
            const method = route.request().method()
            if (method === 'GET') {
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(handle.current),
                })
            } else if (method === 'PATCH') {
                const patch = route.request().postDataJSON() ?? {}
                handle.current = { ...handle.current, ...patch }
                if (patch.enabled === true && handle.current.first_enabled_at == null) {
                    handle.current.first_enabled_at = new Date().toISOString()
                }
                await route.fulfill({
                    status: 200,
                    contentType: 'application/json',
                    body: JSON.stringify(handle.current),
                })
            } else if (method === 'DELETE') {
                await route.fulfill({ status: 204 })
            } else {
                await route.continue()
            }
        }
    )

    await page.route(
        (url) => /\/api\/projects\/[^/]+\/hog_functions\/?/.test(url.pathname),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ results: [], count: 0, next: null }),
            })
        }
    )

    await page.route(
        (url) => /\/api\/environments\/[^/]+\/logs\/sparkline\/?/.test(url.pathname),
        async (route) => {
            await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
        }
    )

    await page.route(
        (url) => /\/api\/projects\/[^/]+\/integrations\/?$/.test(url.pathname),
        async (route) => {
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ results: [], count: 0, next: null }),
            })
        }
    )

    return { alert: handle }
}

async function gotoAlertsList(page: Page): Promise<void> {
    await page.goto('/project/1/logs?activeTab=alerts')
    await page.evaluate(() => void (window as any).posthog?.reloadFeatureFlags?.())
    await expect(page.getByTestId('logs-alerts-new')).toBeVisible({ timeout: 15000 })
}

async function clickNewAlert(page: Page): Promise<void> {
    await page.getByTestId('logs-alerts-new').click()
    await page.waitForURL(new RegExp(`/logs/alerts/${MOCK_ALERT_ID}`), { timeout: 15000 })
    await expect(page.getByTestId('logs-alert-threshold-count')).toBeVisible({ timeout: 15000 })
}

async function addErrorSeverityFilter(page: Page): Promise<void> {
    const trigger = page.getByTestId('logs-severity-filter')
    await trigger.click()
    const option = page.getByTestId('logs-severity-option-error')
    await expect(option).toBeVisible({ timeout: 5000 })
    await option.click()
    await page.keyboard.press('Escape')
    await expect(trigger).toContainText(/error/i, { timeout: 5000 })
}

test.describe('Logs Alerts', () => {
    test.beforeEach(async ({ page }) => {
        await mockFeatureFlags(page, { 'logs-tabbed-view': true, 'logs-alerting': true })
    })

    test('golden creation flow: click-to-create → filter → Enable anyway → flips to enabled', async ({ page }) => {
        await setupAlertMocks(page)

        await test.step('click-to-create lands on detail page in draft state', async () => {
            await gotoAlertsList(page)
            await clickNewAlert(page)
            await expect(page.getByTestId('scene-title-textarea')).toBeVisible()
            await expect(page.getByTestId('logs-alert-enable-primary')).toBeVisible()
            await expect(page.getByTestId('logs-alert-toggle-enabled')).toHaveCount(0)
            await expect(page.getByTestId('logs-alert-save-primary')).toHaveCount(0)
            await expect(page.getByTestId('logs-alert-banner-enable').first()).toBeVisible()
        })

        await test.step('Enable alert is disabled without filters', async () => {
            await expect(page.getByTestId('logs-alert-enable-primary')).toBeDisabled()
        })

        await test.step('add severity filter then Enable alert opens warning dialog', async () => {
            await addErrorSeverityFilter(page)
            await expect(page.getByTestId('logs-alert-enable-primary')).toBeEnabled()

            await page.getByTestId('logs-alert-enable-primary').click()
            await expect(page.getByTestId('logs-alert-warning-enable-anyway')).toBeVisible({ timeout: 10000 })
        })

        await test.step('Enable anyway flips alert to enabled (Save replaces Enable alert)', async () => {
            await page.getByTestId('logs-alert-warning-enable-anyway').click()
            await expect(page.getByTestId('logs-alert-save-primary')).toBeVisible({ timeout: 10000 })
            await expect(page.getByTestId('logs-alert-toggle-enabled')).toBeVisible()
            await expect(page.getByTestId('logs-alert-banner-enable')).toHaveCount(0)
        })
    })

    test('disabled-banner Enable button works on a dirty draft (regression for save-then-enable)', async ({ page }) => {
        await setupAlertMocks(page)

        await gotoAlertsList(page)
        await clickNewAlert(page)
        await addErrorSeverityFilter(page)

        await test.step('banner Enable opens warning dialog (no filter-required toast, no 400)', async () => {
            await page.getByTestId('logs-alert-banner-enable').first().click()
            await expect(page.getByTestId('logs-alert-warning-configure-notifications')).toBeVisible({
                timeout: 10000,
            })
            await expect(page.getByText(/at least one filter is required/i)).toHaveCount(0)
            await expect(page.getByText(/failed to update alert/i)).toHaveCount(0)
        })
    })
})
