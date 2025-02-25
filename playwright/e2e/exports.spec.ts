import { expect, test } from '../utils/playwright-test-base'

test.describe('Exporting Insights', () => {
    test.beforeEach(async ({ page }) => {
        // Enable 'export-dashboard-insights' or replicate
        // Then visit new insight
        await page.goto('/insights/new')

        // apply a filter
        await page.locator('[data-attr$=add-filter-group]').click()
        // ...
        await page.click('[data-attr="insight-save-button"]')
    })

    test('Export an Insight to png', async ({ page }) => {
        // test that we can click "Export" => "Export to PNG"
        await expect(page.locator('[data-attr="insight-edit-button"]')).toBeVisible()
        await page.locator('.TopBar3000 [data-attr=more-button]').click()
        await page.locator('.Popover [data-attr=export-button]').click()
        await page.locator('[data-attr=export-button-png]').click()

        // confirm no popovers
        await page.waitForTimeout(500)
        await expect(page.locator('.Popover')).toHaveCount(0)

        // if you do snapshot comparisons of the downloaded PNG, you'd do `page.waitForEvent('download')`
    })
})
