import { expect, test } from '../utils/playwright-test-base'

test.describe('Notebooks + Insights', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('notebooks')
        await expect(page).toHaveURL(/notebooks/)
    })

    test('Can add a HogQL insight', async ({ page }) => {
        // create a new HogQL insight
        await page.goto('/saved_insights')
        await page.locator('[data-attr=saved-insights-new-insight-dropdown]').click()
        await page.locator('[data-attr-insight-type="SQL"]').click()
        await page.locator('[data-attr="top-bar-name"] button').click()
        await page.locator('[data-attr="top-bar-name"] input').fill('SQL Insight')
        await page.locator('[data-attr="top-bar-name"] button[title="Save"]').click()
        await page.locator('[data-attr="insight-save-button"]').click()

        // create new notebook
        await page.locator('[data-attr="notebooks-add-button"]').click()
        await page.locator('[data-attr="notebooks-select-button-create"]').click()
        await expect(page.locator('.ErrorBoundary')).toHaveCount(0)

        // confirm no table settings in the block
        await expect(page.locator('[data-attr="notebook-node-query"] [data-attr="export-button"]')).toHaveCount(0)
    })
})
