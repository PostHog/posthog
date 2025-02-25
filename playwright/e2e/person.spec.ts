import { expect, test } from '../utils/playwright-test-base'

test.describe('Person Visualization', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('personsmanagement')
        await expect(page).toHaveURL(/\/persons/)
        await page.fill('[data-attr=persons-search]', 'deb')
        await page.waitForTimeout(1000)
        // no result from cypress? We'll just guess
        // ...
        // select the person
    })

    test('Can access person page', async ({ page }) => {
        // you might do:
        // await page.locator('tr', { hasText: 'deborah.fernandez@gmail.com' }).click()
        // test for existence
        // ...
        await expect(page.locator('[data-row-key="email"]')).toContainText('email')
    })

    test('Does not show "Person" column in events table', async ({ page }) => {
        await page.locator('role=tab', { name: 'Events' }).click()
        // click the first event
        await page.locator('table tr td:first-child').click()
        await expect(page.locator('table')).not.toContainText('Person')
    })
})
