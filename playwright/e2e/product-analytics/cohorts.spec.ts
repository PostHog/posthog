import { CohortPage } from '../../page-models/cohortPage'
import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Cohorts', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')

        await expect(page).toHaveTitle('Cohorts • People • PostHog')
        await expect(page.locator('[data-attr="create-cohort"]')).toBeVisible()
        await expect(page.locator('[data-attr="product-introduction-docs-link"]')).toHaveText(/Learn more/)
    })

    test('Can create a cohort', async ({ page }) => {
        const name = randomString('Test-Cohort-')

        await new CohortPage(page).createCohort(name)

        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')

        await expect(page.locator('tbody')).toContainText(name)
    })

    // works locally fails in CI
    test.skip('Duplicate a cohort', async ({ page }) => {
        const name = randomString('Test-Cohort-')

        await new CohortPage(page).createCohort(name)

        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')

        // navigate to the page
        await page.click('tbody >> text=' + name)
        await expect(page.getByTestId('top-bar-name').getByText('Test-Cohort--')).toBeVisible()
        await page.click('.TopBar3000 [data-attr="more-button"]', { force: true })
        // click edit
        await page.click('.Popover__content >> text=Duplicate as dynamic cohort')
        await page.click('.Toastify__toast-body >> text=View cohort')

        await page.click('.TopBar3000 [data-attr="more-button"]')
        await page.click('.Popover__content >> text=Duplicate as static cohort')
        await page.click('.Toastify__toast-body >> text=View cohort')

        await page.click('[data-attr="more-button"]')
        await page.click('.Popover__content >> text=Delete cohort')

        await page.goToMenuItem('personsmanagement')
        await page.click('[data-attr=persons-management-cohorts-tab]')

        await expect(page.locator('tbody')).not.toContainText(name + ' (dynamic copy) (static copy)')
    })
})
