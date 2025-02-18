import { test, expect } from '../utils/playwright-test-base'

test.describe('Person Visualization Check', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('personsmanagement')
        await expect(page).toHaveURL(/.*\/persons/)
        await page.waitForTimeout(1000)
        await page.locator('[data-attr=persons-search]').fill('deb')
        await expect(page.locator('[data-attr=persons-search]')).toHaveValue('deb')
        await expect(page.locator('text=deborah.fernandez@gmail.com')).not.toBeVisible()
        await page.locator('text=deborah.fernandez@gmail.com').click()
        await page.waitForTimeout(1000)
    })

    test('Can access person page', async ({ page }) => {
        await expect(page.locator('[data-row-key="email"] > :nth-child(1)')).toContainText('email')
        await page.locator('[data-row-key="email"] [data-attr=copy-icon]').click()
        await page.locator('[role="tab"]:has-text("Events")').click()
        await expect(page.locator('table')).toContainText('Event')
    })

    test('Does not show the Person column', async ({ page }) => {
        await page.locator('[role="tab"]:has-text("Events")').click()
        await page.locator('table').locator('text=Event').click()
        await expect(page.locator('table')).not.toContainText('Person')
    })
})
