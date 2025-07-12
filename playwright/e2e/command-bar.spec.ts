import { expect, test } from '../utils/playwright-test-base'

test.describe('Command Bar', () => {
    test('Handles keyboard shortcuts', async ({ page }) => {
        /** Show/hide search */
        // show search
        await page.locator('[data-attr="tree-navbar-search-button"]').waitFor()
        await page.keyboard.press('Control+K')
        await expect(page.locator('[data-attr=search-bar-input]')).toBeVisible()

        // hide search with esc
        await page.keyboard.press('Escape')
        await expect(page.locator('[data-attr=search-bar-input]')).not.toBeVisible()

        /** Show/hide actions */
        // show actions
        await page.keyboard.press('Control+Shift+K')
        await expect(page.locator('[data-attr=action-bar-input]')).toBeVisible()

        // hide actions with esc
        await page.keyboard.press('Escape')
        await expect(page.locator('[data-attr=action-bar-input]')).not.toBeVisible()

        /** Show/hide shortcuts */
        // show shortcuts
        await page.keyboard.press('Shift+?')
        await expect(page.locator('text=Keyboard shortcuts')).toBeVisible()

        // hide shortcuts with esc
        await page.keyboard.press('Escape')
        await expect(page.locator('text=Keyboard shortcuts')).not.toBeVisible()
    })
})
