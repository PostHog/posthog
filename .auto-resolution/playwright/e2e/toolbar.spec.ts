import { expect, test } from '../utils/playwright-test-base'

test.describe('Toolbar', () => {
    test.skip('Toolbar loads', async ({ page }) => {
        await page.goToMenuItem('toolbar')
        await page.getByText('Add authorized URL').click()

        const loc = await page.evaluate(() => window.location)
        await page.locator('[data-attr="url-input"]').fill(`http://${loc.host}/demo`)
        await page.locator('[data-attr="url-save"]').click()

        const href = await page.locator('[data-attr="toolbar-open"]').first().getAttribute('href')
        if (href) {
            await page.goto(href)
        }

        await expect(page.locator('#__POSTHOG_TOOLBAR__ .Toolbar')).toBeVisible({ timeout: 5000 })
    })

    test('Toolbar item in sidebar has launch options', async ({ page }) => {
        await page.goToMenuItem('toolbar')
        await page.getByText('Add authorized URL').click()
        await expect(page).toHaveURL(/.*\/toolbar/)
    })
})
