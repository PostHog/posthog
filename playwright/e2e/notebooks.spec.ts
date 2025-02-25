import { expect, test } from '../utils/playwright-test-base'

test.describe('Notebooks', () => {
    test.beforeEach(async ({ page }) => {
        // mock session recording intercept
        await page.goto('/notebooks')
    })

    test('Notebooks are enabled, can create new, insert content', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Notebooks')
        // create new
        await page.locator('[data-attr="new-notebook"]').click()
        await expect(page.locator('.NotebookEditor')).toBeVisible()

        // Insert bullet list
        await page.keyboard.type('* bullet 1')
        await page.keyboard.press('Enter')
        await page.keyboard.type('bullet 2')
        await expect(page.locator('ul')).toContainText('bullet 1')
        await expect(page.locator('ul')).toContainText('bullet 2')
    })
})
