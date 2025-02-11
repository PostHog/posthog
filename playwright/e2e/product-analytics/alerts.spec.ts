import { expect, Page, test } from '@playwright/test'
import { Compression, DecideResponse } from 'posthog-js'
import { InsightPage } from '../../page-models/insightPage'

export function decideResponse(featureFlags: Record<string, string | boolean>): DecideResponse {
    return {
        toolbarParams: {
            toolbarVersion: 'toolbar',
        },
        isAuthenticated: true,
        supportedCompression: [Compression.GZipJS],
        hasFeatureFlags: Object.keys(featureFlags).length > 0,
        featureFlags,
        featureFlagPayloads: {},
        errorsWhileComputingFlags: false,
        sessionRecording: {
            endpoint: '/s/',
        },
        toolbarVersion: 'toolbar',
        siteApps: [],
    }
}

export const setupFeatureFlags = async (page: Page, overrides = {}): Promise<void> => {
    await page.route('**/array/*/config', (route) =>
        route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(decideResponse({ ...overrides })),
        })
    )

    await page.route('**/array/*/config.js', async (route) => {
        const response = await route.fetch()
        await route.fulfill({
            response,
        })
    })

    await page.route('**/decide/*', (route) =>
        route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(decideResponse({ ...overrides })),
        })
    )
}

test.describe('Alerts', () => {
    test.beforeEach(async ({ page }) => {
        await setupFeatureFlags(page, {
            alerts: true,
        })
        await new InsightPage(page).createNew('insight')
    })

    const createAlert = async (
        page: Page,
        name: string = 'Alert name',
        lowerThreshold: string = '100',
        upperThreshold: string = '200',
        condition?: string
    ): Promise<void> => {
        await page.getByText('Alerts').click()
        await page.getByText('New alert').click()

        await page.locator('[data-attr=alertForm-name]').fill(name)
        await page.locator('[data-attr=subscribed-users]').click()
        await page.keyboard.press('ArrowDown')
        await page.keyboard.press('Enter')

        if (condition) {
            await page.locator('[data-attr=alertForm-condition]').click()
            await page.getByText(condition).click()
            await page.getByText('%').click()
        }

        await page.locator('[data-attr=alertForm-lower-threshold]').fill(lowerThreshold)
        await page.locator('[data-attr=alertForm-upper-threshold]').fill(upperThreshold)
        await page.getByText('Create alert').click()
        await expect(page.locator('.Toastify__toast-body')).toContainText('Alert created.')
        await expect(page).not.toHaveURL(/\/new/)
        await expect(page.locator('[data-attr=alert-list-item]').getByText(name)).toBeVisible()

        await page.getByText('Close', { exact: true }).click()
    }

    const setInsightDisplayTypeAndSave = async (page: Page, displayType: string): Promise<void> => {
        await page.locator('[data-attr=insight-edit-button]').click()
        await page.locator('[data-attr=chart-filter]').click()
        await page.getByText(displayType).click()
        await page.locator('[data-attr=insight-save-button]').getByText('Save').click()
        await expect(page).not.toHaveURL(/\/edit/)
    }

    test('Should allow create and delete an alert', async ({ page }) => {
        await expect(page.getByText('Alerts')).toHaveAttribute('aria-disabled', 'true')

        await setInsightDisplayTypeAndSave(page, 'Number')
        await createAlert(page)
        await page.reload()

        await page.getByText('Alerts').click()
        await page.locator('[data-attr=alert-list-item]').getByText('Alert name').click()
        await expect(page.locator('[data-attr=alertForm-name]')).toHaveValue('Alert name')
        await expect(page.locator('[data-attr=alertForm-lower-threshold]')).toHaveValue('100')
        await expect(page.locator('[data-attr=alertForm-upper-threshold]')).toHaveValue('200')
        await page.getByText('Delete alert').click()
        await page.waitForTimeout(2000)
        await page.reload()
        await expect(page.getByText('Alert name')).not.toBeVisible()
    })

    test('Should warn about an alert deletion', async ({ page }) => {
        await setInsightDisplayTypeAndSave(page, 'Area chart')
        await createAlert(page, 'Alert to be deleted because of a changed insight')

        await page.locator('[data-attr=insight-edit-button]').click()
        await page.getByText('Funnels').click()

        await expect(page.getByText('the existing alerts will be deleted')).toBeVisible()
        await page.getByText('Trends').click()
        await expect(page.getByText('the existing alerts will be deleted')).not.toBeVisible()

        await page.getByText('Funnels').click()
        await page.locator('[data-attr=insight-save-button]').getByText('Save').click()
        await page.getByText('Alerts').click()
        await expect(page.getByText('Alert to be deleted because of a changed insight')).not.toBeVisible()
    })
})
