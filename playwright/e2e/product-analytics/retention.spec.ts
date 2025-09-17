import { urls } from 'scenes/urls'

import { expect, test } from '../../utils/playwright-test-base'

test.describe('Retention', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto(urls.insightNew())
        await page.click('[data-attr=insight-retention-tab]')
    })

    test.skip('should apply retention filter', async ({ page }) => {
        // KLUDGE: this had commented lines in Cypress, they've been copied here _and not tested_
        // NOTE: First wait for results to load, try and make the test more
        // stable. This is to try and avoid an issue where after selecting a
        // filter property, the results section would be blank
        await expect(page.locator('[data-attr=retention-table]')).toBeVisible()

        // Apply filter
        await page.click('[data-attr$=add-filter-group]')
        await page.click('[data-attr=property-select-toggle-0]')
        await page.click('[data-attr=taxonomic-filter-searchfield]')
        await page.fill('[data-attr=taxonomic-filter-searchfield]', 'is_demo')
        await page.click('[data-attr=taxonomic-tab-event_properties]')
        await page.click('[data-attr=prop-filter-event_properties-0]')
        await page.locator('[data-attr=prop-val]').fill('true')
        await expect(page.locator('[data-attr=retention-table]')).toBeVisible()

        // Uncomment and adapt the following lines if needed
        // await page.locator('.percentage-cell').last().click()
        // await expect(page.locator('[data-attr=retention-person-link]')).toHaveCount(1)
        // await expect(page.locator('[data-attr=retention-person-link]')).toContainText('smith.nunez@gmail.com')
        // await page.click('[data-attr=retention-person-link]')
        // await expect(page).toHaveURL(/\/person\//)
        // await expect(page.locator('text=smith.nunez@gmail.com')).toBeVisible()
    })
})
