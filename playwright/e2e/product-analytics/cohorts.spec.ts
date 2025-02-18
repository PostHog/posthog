import { expect, test } from '../../utils/playwright-test-base'
import { randomString } from '../../utils'

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
        await page.locator('[data-attr=prop-val]').type('true')

        await page.click('[data-attr="cohort-name"]')

        const name = randomString('Test-Cohort-')

        await page.fill('[data-attr="cohort-name"]', name)
        await page.click('[data-attr="save-cohort"]')
        await expect(page.locator('[data-attr=success-toast]')).toHaveText(/Cohort saved/)
        await page.locator('[data-attr="toast-close-button"]').click()

        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')

        await expect(page.locator('tbody')).toContainText(name)
        await expect(page.locator('text=Create your first cohort')).not.toBeVisible()

        // navigate to the page
        await page.click('tbody >> text=' + name)
        await expect(page.getByTestId('top-bar-name').getByText('Test-Cohort--')).toBeVisible()
        await page.click('[data-attr="more-button"]', { force: true })
        // click edit
        await page.locator('.Popover__content a').first().click()

        await page.click('.Popover__content >> text=Duplicate as dynamic cohort')
        await page.click('.Toastify__toast-body >> text=View cohort')

        await page.click('[data-attr="more-button"]')
        await page.click('.Popover__content >> text=Duplicate as static cohort')
        await page.click('.Toastify__toast-body >> text=View cohort')

        await page.click('[data-attr="more-button"]')
        await page.click('.Popover__content >> text=Delete cohort')

        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')

        await expect(page.locator('tbody')).not.toContainText(name + ' (dynamic copy) (static copy)')
    })
})
