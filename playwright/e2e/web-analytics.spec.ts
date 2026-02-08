import { expect, test } from '../utils/playwright-test-base'

test.describe('Web Analytics', () => {
    test('Can open add authorized URL form', async ({ page }) => {
        await page.goto('/web')
        // Open the domain filter dropdown
        await page.getByText('All domains').click()
        // Click the add button in the dropdown footer
        await page.getByText('Add authorized URL').click()
        await expect(page.locator('[data-attr="web-authorized-url-input"]')).toBeVisible()
    })
})
