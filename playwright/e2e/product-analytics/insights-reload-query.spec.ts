import { expect, test } from '../../utils/playwright-test-base'

test.describe('ReloadInsight component', () => {
    test('saves the query to the URL/localStorage and reloads it if user left unsaved', async ({ page }) => {
        // In cypress we check localStorage, in Playwright we can do page.evaluate
        await page.goto('/insights/new')

        // do some changes
        await page.locator('[data-attr="math-selector-0"]').click()
        await page.locator('[data-attr="math-dau-0"]').click()

        // confirm that localStorage has draft
        const draftQuery = await page.evaluate(() => localStorage.getItem('draft-query-<TEAM_ID>'))
        expect(draftQuery).not.toBeNull()

        // navigate away
        await page.goto('/saved_insights')
        await expect(page.locator('text=You have an unsaved insight')).toBeVisible()
        await page.locator('text=Click here').click()
        // confirm it loaded
        await expect(page.locator('[data-attr="math-selector-0"]')).toHaveText('Unique users')
    })
})
