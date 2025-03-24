import { expect, test } from '../utils/playwright-test-base'

test.describe('Project Homepage', () => {
    test('Shows home dashboard on load', async ({ page }) => {
        await page.goToMenuItem('projecthomepage')
        await expect
            .poll(async () => {
                return await page.locator('[data-attr=insight-card]').count()
            })
            .toBeGreaterThan(1)
    })
})
