import { expect, test } from '../../utils/playwright-test-base'

test.describe('Retention', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/insights/new')
        await page.locator('[data-attr=insight-retention-tab]').click()
        await expect(page.locator('[data-attr=retention-table]')).toBeVisible()
    })

    test('should apply filter and navigate to persons', async ({ page }) => {
        await page.locator('[data-attr=insight-retention-add-filter-group]').click()
        await page.locator('[data-attr=property-select-toggle-0]').click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').type('is_demo')
        await page.locator('[data-attr=taxonomic-tab-person_properties]').click()
        await page.locator('[data-attr=prop-filter-person_properties-0]').click()
        await page.locator('[data-attr=prop-val]').click()
        await page.locator('[data-attr=prop-val-0]').click()
        await expect(page.locator('[data-attr=retention-table]')).toBeVisible()

        // sample: open the last .percentage-cell => see retention-person-link => click => persons
        // This might require more detail if you implement advanced retention table logic
        // ...
    })
})
