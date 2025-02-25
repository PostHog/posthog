import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Duplicating insights', () => {
    let insightName: string

    test.beforeEach(async ({ page }) => {
        // create new insight with some name
        insightName = randomString('insight-name-')
        await page.goto('/saved_insights')
        await page.locator('[data-attr=saved-insights-new-insight-dropdown]').click()
        await page.locator('[data-attr-insight-type="TRENDS"]').click()
        await page.locator('[data-attr="top-bar-name"] button').click()
        await page.locator('[data-attr="top-bar-name"] input').fill(insightName)
        await page.locator('[data-attr="top-bar-name"] [title="Save"]').click()
        await page.locator('[data-attr="insight-save-button"]').click()
        await expect(page).not.toHaveURL(/\/new/)
    })

    test('can duplicate from the insights list view', async ({ page }) => {
        await page.goto('/saved_insights')
        const row = page.locator('.saved-insights table tr', { hasText: insightName })
        await row.locator('[data-attr="more-button"]').click()
        await page.locator('[data-attr="duplicate-insight-from-list-view"]').click()
        await expect(page.locator('.saved-insights table tr')).toContainText(`${insightName} (copy)`)
    })

    test('can duplicate from insight view', async ({ page }) => {
        await page.locator('.TopBar3000 [data-attr="more-button"]').click()
        await page.locator('[data-attr="duplicate-insight-from-insight-view"]').click()
        await expect(page.locator('[data-attr="top-bar-name"] .EditableField__display')).toContainText(
            `${insightName} (copy)`
        )
    })

    test('can save insight as a copy', async ({ page }) => {
        await page.locator('[data-attr="insight-edit-button"]').click()
        await page.locator('[data-attr="insight-save-dropdown"]').click()
        await page.locator('[data-attr="insight-save-as-new-insight"]').click()
        await page.locator('button[type=submit]').click()
        await expect(page.locator('[data-attr="top-bar-name"] .EditableField__display')).toContainText(
            `${insightName} (copy)`
        )
    })
})
