import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Insights navigation', () => {
    test('can save and load a SQL insight, then switch to retention', async ({ page }) => {
        // new SQL
        await page.goto('/insights')
        await page.locator('[data-attr="saved-insights-new-insight-dropdown"]').click()
        await page.locator('[data-attr-insight-type="SQL"]').click()
        const insightName = randomString('SQL insight')
        await page.locator('[data-attr="top-bar-name"] button').click()
        await page.locator('[data-attr="top-bar-name"] input').fill(insightName)
        await page.locator('[data-attr="top-bar-name"] button[title="Save"]').click()
        await page.locator('[data-attr="insight-save-button"]').click()
        await expect(page).not.toHaveURL(/\/new$/)

        // go to saved insights
        await page.goto('/saved_insights')
        await page.locator('.saved-insights tr', { hasText: insightName }).locator('.Link').click()

        // now switch from SQL to retention
        await page.locator('[data-attr="insight-edit-button"]').click()
        await page.locator('[data-attr="insight-retention-tab"]').click()
        await page.locator('[data-attr="insight-save-button"]').click()

        await expect(page.locator('.RetentionContainer canvas')).toBeVisible()
        await expect(page.locator('.RetentionTable__Tab')).toHaveCount(36)
    })
})
