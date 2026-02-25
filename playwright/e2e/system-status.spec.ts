import { expect, test } from '../utils/playwright-test-base'

test.describe('System Status', () => {
    test('System Status loaded', async ({ page }) => {
        await page.goto('/instance/status')
        await expect(page.locator('table')).toHaveText(/Events in ClickHouse/)
    })
})
