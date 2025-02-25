import { expect, test } from '../../utils/playwright-test-base'

test.describe('Opening a new insight directly', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/insights/new')
    })

    test('Can open a new TRENDS insight', async ({ page }) => {
        await page.locator('[data-attr="insight-trends-tab"]').click()
        await expect(page.locator('.TrendsInsight canvas')).toBeVisible()
        await expect(page.locator('tr')).toHaveCountGreaterThan(1)
    })

    test('Can open a new FUNNELS insight', async ({ page }) => {
        await page.locator('[data-attr="insight-funnels-tab"]').click()
        await expect(page.locator('[data-attr="insight-empty-state"]')).toContainText('Add steps to build a funnel')
    })

    // etc. for PATHS, STICKINESS, LIFECYCLE, SQL
})
