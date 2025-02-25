import { expect, test } from '../../utils/playwright-test-base'

test.describe('Insights date picker', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/insights/new')
        // wait for network idle or for something
    })

    test('Can set the date filter and show the right grouping interval', async ({ page }) => {
        await page.locator('[data-attr=date-filter]').click()
        await page.locator('text=Yesterday').click()
        await expect(page.locator('[data-attr=interval-filter] .LemonButton__content')).toContainText('hour')
    })

    test('Can set a custom rolling date range', async ({ page }) => {
        await page.locator('[data-attr=date-filter]').click()
        await page.locator('.Popover [data-attr=rolling-date-range-input]').fill('5')
        await page.locator('.Popover [data-attr=rolling-date-range-date-options-selector]').click()
        await page.locator('.RollingDateRangeFilter__popover').getByText('days').click()
        await expect(page.locator('.Popover .RollingDateRangeFilter__label')).toContainText('In the last')

        // The button should show "Last 5 days"
        await expect(page.locator('[data-attr=date-filter] .LemonButton__content')).toContainText('Last 5 days')
    })
})
