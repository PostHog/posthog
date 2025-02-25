import { expect, test } from '../../utils/playwright-test-base'

test.describe('Paths', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/insights/new')
        await page.locator('[data-attr=insight-path-tab]').click()
    })

    test('Paths loaded', async ({ page }) => {
        await expect(page.locator('[data-attr=paths-viz]')).toBeVisible()
    })

    test('Apply date filter', async ({ page }) => {
        await page.locator('[data-attr=date-filter]').click()
        await page.locator('text=Last 30 days').click()
        await expect(page.locator('[data-attr=paths-viz]')).toBeVisible()
    })
})
