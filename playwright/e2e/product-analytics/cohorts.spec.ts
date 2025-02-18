import { expect, test } from '../../utils/playwright-test-base'

test.describe('Cohorts', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')
    })

    test('Cohorts new and list', async ({ page }) => {
        await expect(page).toHaveTitle('Cohorts • People • PostHog')
        await expect(page.locator('[data-attr="create-cohort"]')).toBeVisible()
        await expect(page.locator('[data-attr="product-introduction-docs-link"]')).toHaveText(/Learn more/)

        await page.click('[data-attr="new-cohort"]')
        await page.click('[data-attr="cohort-selector-field-value"]')
        await page.click('[data-attr="cohort-personPropertyBehavioral-have_property-type"]')
        await page.click('[data-attr="cohort-taxonomic-field-key"]')

        await page.click('[data-attr=prop-filter-person_properties-0]', { force: true })
        await page.click('[data-attr=prop-val]')
        await page.click('[data-attr=prop-val-0]', { force: true })
        await page.click('[data-attr="cohort-name"]')

        await page.fill('[data-attr="cohort-name"]', 'Test Cohort')
        await page.click('[data-attr="save-cohort"]')
        await expect(page.locator('[data-attr=success-toast]')).toHaveText(/Cohort saved/)

        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')

        await expect(page.locator('tbody')).toContainText('Test Cohort')
        await expect(page.locator('text=Create your first cohort')).not.toBeVisible()

        await page.click('tbody >> text=Test Cohort')
        await page.click('[data-attr="more-button"]')
        await page.click('.Popover__content >> text=Duplicate as dynamic cohort')
        await page.click('.Toastify__toast-body >> text=View cohort')

        await page.click('[data-attr="more-button"]')
        await page.click('.Popover__content >> text=Duplicate as static cohort')
        await page.click('.Toastify__toast-body >> text=View cohort')

        await page.click('[data-attr="more-button"]')
        await page.click('.Popover__content >> text=Delete cohort')

        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')

        await expect(page.locator('tbody')).not.toContainText('Test Cohort (dynamic copy) (static copy)')
    })
})
