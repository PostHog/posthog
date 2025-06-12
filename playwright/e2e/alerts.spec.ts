import { Page } from '@playwright/test'

import { randomString } from '../utils'
import { mockFeatureFlags } from '../utils/mockApi'
import { expect, test } from '../utils/playwright-test-base'

/** ---------------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------------ */

/** Creates a new saved trends insight and returns its name. */
const createTrendsInsight = async (page: Page, name: string): Promise<void> => {
    // Go straight to the blank insight screen
    await page.goto('/insights/new')

    // Give it a name…
    await page.locator('[data-attr="top-bar-name"] button').click()
    await page.locator('[data-attr="top-bar-name"] input').fill(name)
    await page.keyboard.press('Enter')

    // …and save it
    await page.locator('[data-attr="insight-save-button"]').click()
    await page.locator('[data-attr="save-to-modal-save-button"]').click()
    await expect(page).not.toHaveURL(/\/new$/)
}

/** Changes the display type (Chart → Number, Pie, Bar … ) and saves the insight. */
const setInsightDisplayTypeAndSave = async (page: Page, displayType: string): Promise<void> => {
    await page.locator('[data-attr="insight-edit-button"]').click()
    await page.waitForTimeout(300)
    await page.locator('[data-attr="chart-filter"]').click({ force: true })
    await page.waitForTimeout(300)
    await page.locator('.Popover button', { hasText: new RegExp(`.*${displayType}.*`, 'i') }).click({ force: true })
    await page.waitForTimeout(300)
    await page.locator('[data-attr="insight-save-button"]').first().click()
    await expect(page).not.toHaveURL(/\/edit$/)
}

const closeToast = async (page: Page): Promise<void> => {
    const closeBtn = page.locator("button[data-attr='toast-close-button']").first()

    if (await closeBtn.count()) {
        await closeBtn.click()
    }
}

async function clickLastVisible(locator: import('@playwright/test').Locator): Promise<void> {
    const total = await locator.count()
    for (let i = total - 1; i >= 0; i--) {
        const candidate = locator.nth(i)
        if (await candidate.isVisible()) {
            await candidate.click()
            return
        }
    }
    throw new Error('No visible element matched the locator – nothing to click')
}

/** Creates an alert on the currently-open insight. */
const createAlert = async (
    page: Page,
    {
        name = 'Alert name',
        lowerThreshold = '100',
        upperThreshold = '200',
        condition,
    }: {
        name?: string
        lowerThreshold?: string
        upperThreshold?: string
        condition?: string
    } = {}
): Promise<void> => {
    await page.locator('[data-attr="manage-alerts-button"]').click()
    await page.getByText('New alert').click()

    await page.locator('[data-attr=alertForm-name]').fill(name)

    // Subscribe current user
    await page.locator('[data-attr=subscribed-users]').click()
    await page.keyboard.press('ArrowDown')
    await page.keyboard.press('Enter')

    if (condition) {
        await page.locator('[data-attr=alertForm-condition]').click()
        await page.getByText(condition, { exact: true }).click()
        await page.getByText('%').click()
    }

    await page.locator('[data-attr=alertForm-lower-threshold]').click()
    await page.locator('[data-attr=alertForm-lower-threshold]').fill(lowerThreshold)
    await page.locator('[data-attr=alertForm-upper-threshold]').click()
    await page.locator('[data-attr=alertForm-upper-threshold]').fill(upperThreshold)
    await page.waitForTimeout(100)
    await closeToast(page)
    // We have two modals in the dom, with one overlaying the other.
    await page.getByRole('button', { name: 'Create alert' }).click()
    await page.waitForTimeout(100)
    await expect(page.locator('.Toastify__toast-body', { hasText: 'Alert created.' })).toBeVisible()
    await expect(page).not.toHaveURL(/\/new$/)
    await page.waitForTimeout(100)

    // Alert list should contain the new one
    await expect(page.locator('[data-attr=alert-list-item]')).toContainText(name)

    // Close the slide-over. We have two modals in the dom, with one overlaying the other.
    await clickLastVisible(page.locator('[data-attr="lemon-modal-close-button"]'))
    await page.waitForTimeout(100)
    await clickLastVisible(page.locator('[data-attr="lemon-modal-close-button"]'))
}

/** Deletes the first alert in the list (assumes the details drawer is open). */
const deleteCurrentAlert = async (page: Page): Promise<void> => {
    await page.getByRole('button', { name: 'Delete alert' }).click()
    // Small toast appears – wait for it to disappear before continuing
    await page.waitForTimeout(2000)
}

/** ---------------------------------------------------------------------------
 * Tests
 * ------------------------------------------------------------------------ */

test.describe('Alerts', () => {
    let insightName: string

    test.beforeEach(async ({ page }) => {
        // Feature-flag the Alerts product on
        await mockFeatureFlags(page, { alerts: true })

        // Create a fresh insight for every test
        insightName = randomString('alerts-insight')
        await createTrendsInsight(page, insightName)
    })

    test('can create and delete a basic alert', async ({ page }) => {
        // Alerts are disabled on graph visualisations
        await expect(page.locator('[data-attr="manage-alerts-button"]')).toHaveAttribute('aria-disabled', 'true')

        // Switch to “Number” display so Alerts are enabled
        await setInsightDisplayTypeAndSave(page, 'Number')

        // Create an alert and double-check it’s saved
        await createAlert(page)
        await page.reload()

        await page.locator('[data-attr="manage-alerts-button"]').click()
        await page.locator('[data-attr=alert-list-item]').getByText('Alert name').click()
        await expect(page.locator('[data-attr=alertForm-name]')).toHaveValue('Alert name')
        await expect(page.locator('[data-attr=alertForm-lower-threshold]')).toHaveValue('100')
        await expect(page.locator('[data-attr=alertForm-upper-threshold]')).toHaveValue('200')

        // Delete it
        await deleteCurrentAlert(page)
        await page.reload()
        await expect(page.getByText('Alert name')).toHaveCount(0)
    })

    test('shows a warning when the insight becomes incompatible', async ({ page }) => {
        page.on('dialog', (dialog) => dialog.accept()) // dismiss those annoying popups
        await setInsightDisplayTypeAndSave(page, 'Area chart')
        await createAlert(page, { name: 'Alert to be deleted because of a changed insight' })

        // Change to an incompatible insight type (Funnels)
        await page.locator('[data-attr=insight-edit-button]').click()
        await page.getByText('Funnels').click()
        await expect(page.getByText('the existing alerts will be deleted')).toBeVisible()

        // Revert – banner should disappear
        await page.getByText('Trends').click()
        await expect(page.getByText('the existing alerts will be deleted')).toHaveCount(0)

        // Save as incompatible “Funnels” → alerts should be removed
        await page.getByText('Funnels').click()
        await page.locator('[data-attr=insight-save-button]').first().click()
        await page.waitForTimeout(500)

        // Disabled on funnels
        await expect(page.locator('[data-attr="manage-alerts-button"]')).toHaveAttribute('aria-disabled', 'true')
    })

    test('can create and delete a relative (“increases by”) alert', async ({ page }) => {
        await expect(page.locator('[data-attr="manage-alerts-button"]')).toHaveAttribute('aria-disabled', 'true')

        await setInsightDisplayTypeAndSave(page, 'Trends over time as vertical bars')
        await createAlert(page, {
            lowerThreshold: '10',
            upperThreshold: '20',
            condition: 'increases by',
        })
        await page.reload()

        await page.locator('[data-attr="manage-alerts-button"]').click()
        await page.locator('[data-attr=alert-list-item]').getByText('Alert name').click()
        await expect(page.locator('[data-attr=alertForm-lower-threshold]')).toHaveValue('10')
        await expect(page.locator('[data-attr=alertForm-upper-threshold]')).toHaveValue('20')

        await deleteCurrentAlert(page)
        await page.reload()
        await expect(page.getByText('Alert name')).toHaveCount(0)
    })

    test('supports alerts on insights with breakdowns', async ({ page }) => {
        await setInsightDisplayTypeAndSave(page, 'Trends over time as vertical bars')
        await page.reload()

        // Add a simple breakdown (Browser)
        await page.locator('[data-attr=insight-edit-button]').click()
        await page.locator('[data-attr=add-breakdown-button]').click()
        await page.locator('[data-attr=prop-filter-event_properties-1]').click({ force: true })
        await page.locator('[data-attr="insight-save-button"]').first().click()
        await clickLastVisible(page.locator('[data-attr="insight-cancel-edit-button"]')) // just in case it doesn't close automatically
        await page.waitForTimeout(500)

        await createAlert(page, {
            lowerThreshold: '10',
            upperThreshold: '20',
            condition: 'increases by',
        })
        await page.reload()

        await page.locator('[data-attr="manage-alerts-button"]').click()
        await page.locator('[data-attr=alert-list-item]').getByText('Alert name').click()
        await expect(page.getByText('any breakdown value')).toBeVisible()

        await deleteCurrentAlert(page)
        await page.reload()
        await expect(page.getByText('Alert name')).toHaveCount(0)
    })
})
