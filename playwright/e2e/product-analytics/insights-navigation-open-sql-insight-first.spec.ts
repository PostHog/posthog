import { expect, test } from '../../utils/playwright-test-base'

test.describe('Open a new SQL insight first, then a different tab', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/insights/new')
        await page.locator('[data-attr="insight-sql-tab"]').click()
        // fill the hogql query
        await page
            .locator('[data-attr="hogql-query-editor"] textarea')
            .fill(`select event, count() from events limit 2`)
        await page.locator('[data-attr="hogql-query-editor-save"]').click()
        // wait for results
        await expect(page.locator('tr.DataVizRow')).toHaveCountGreaterThan(1)
    })

    test('Switch to TRENDS and back to SQL and back again', async ({ page }) => {
        await page.locator('[data-attr="insight-trends-tab"]').click()
        await expect(page.locator('.TrendsInsight canvas')).toBeVisible()
        await page.locator('[data-attr="insight-sql-tab"]').click()
        await expect(page.locator('[data-attr="hogql-query-editor"]')).toBeVisible()
        await page.locator('[data-attr="insight-trends-tab"]').click()
        await expect(page.locator('.TrendsInsight canvas')).toBeVisible()
    })
})
