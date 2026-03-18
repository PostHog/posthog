import { expect, test } from '../utils/playwright-test-base'

test.describe('System Status', () => {
    test('System Status loaded', async ({ page }) => {
        await page.locator('[data-attr=help-menu-button]').click()
        await page.locator('[data-attr=help-menu-admin-button]').click()
        await page.locator('[data-attr=help-menu-instance-panel-button]').click()
        await expect(page.locator('table')).toHaveText(/Events in ClickHouse/)
    })
})
