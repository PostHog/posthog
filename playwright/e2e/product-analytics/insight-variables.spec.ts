import { expect, test } from '../../utils/playwright-test-base'

test.describe('insight variables', () => {
    test('show correctly on dashboards', async ({ page }) => {
        // Go to "Insight variables" dashboard.
        await page.goToMenuItem('dashboards')
        await page.getByText('Insight variables').click()

        //

        await expect(page.getByText('asd')).toBeVisible({ timeout: 30000 })
    })
})
