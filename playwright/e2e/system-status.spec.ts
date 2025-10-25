import { expect, test } from '../utils/playwright-test-base'

test.describe('System Status', () => {
    test('System Status loaded', async ({ page }) => {
        await page.locator('[data-attr=menu-item-me]').click()
        await page.locator('[data-attr=top-menu-instance-panel]').click()
        await expect(page.locator('table')).toHaveText(/Events in ClickHouse/)
    })
})
