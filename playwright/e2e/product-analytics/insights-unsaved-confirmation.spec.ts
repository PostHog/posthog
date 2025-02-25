import { expect, test } from '../../utils/playwright-test-base'

test.describe('Unsaved insights confirmation', () => {
    test.beforeEach(async ({ page }) => {
        // pre-check
        await page.goto('/insights')
        await expect(page.locator('.saved-insights tr')).toBeVisible()
    })

    test('move away from an unchanged new insight without confirm()', async ({ page }) => {
        await page.goto('/insights/new')
        // just navigate away
        await page.goToMenuItem('featureflags')
        await expect(page).toHaveURL(/feature_flags/)
    })

    test('Keep editing changed new insight if user rejects confirm', async ({ page }) => {
        // This requires hooking up a page.on('dialog'), but Playwright uses a different approach than Cypress
        // We'll simulate "Reject confirm" via page.dialogs

        await page.goto('/insights/new')
        await page.click('[data-attr=add-action-event-button]')
        // navigate away
        const dialogPromise = page.waitForEvent('dialog')
        await page.goToMenuItem('featureflags')
        const dialog = await dialogPromise
        expect(dialog.type()).toBe('confirm')
        await dialog.dismiss()

        // We remain on the insights page
        await expect(page).toHaveURL(/insights\/new/)
    })

    test('Accept confirm => navigate away from changed new insight', async ({ page }) => {
        await page.goto('/insights/new')
        await page.click('[data-attr=add-action-event-button]')

        const dialogPromise = page.waitForEvent('dialog')
        await page.goToMenuItem('featureflags')
        const dialog = await dialogPromise
        await dialog.accept()

        await expect(page).toHaveURL(/feature_flags/)
    })
})
