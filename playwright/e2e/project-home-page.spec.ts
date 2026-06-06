import { expect, test } from '../utils/playwright-test-base'

test.describe('Project Homepage', () => {
    test('Shows AI-first homepage on load', async ({ page }) => {
        await page.goToMenuItem('projecthomepage')
        await expect(page.locator('[data-attr=homepage-input]')).toBeVisible()
    })
})
