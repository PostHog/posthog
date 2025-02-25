import { DashboardPage } from '../page-models/dashboardPage'
import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Deleting dashboards', () => {
    test('can delete dashboard without deleting the insights', async ({ page }) => {
        await page.goto('/saved_insights') // ensure turbo mode caching
        await page.goToMenuItem('dashboards')

        const dashboardName = randomString('dashboard-')
        const insightName = randomString('insight-')

        // create and go to empty dashboard
        const dashPage = new DashboardPage(page)
        await dashPage.createNew(dashboardName)

        // add an insight
        await page.locator('[data-attr="dashboard-add-graph-header"]').getByText('Add insight').click()
        await page.locator('[data-attr="dashboard-add-new-insight"]').getByText('New insight').click()
        await page.fill('[data-attr="top-bar-name"] input', insightName)
        await page.click('[data-attr="top-bar-name"] button:has-text("Save")')
        await page.click('[data-attr=insight-save-button]:has-text("Save & add to dashboard")')
        await expect(page.locator('[data-attr="insight-save-button"]')).toBeHidden()

        // delete the dashboard
        await page.locator('[data-attr="dashboard-three-dots-options-menu"]').click()
        await page.locator('button', { hasText: 'Delete dashboard' }).click()
        await page.locator('[data-attr="dashboard-delete-submit"]').click()

        // check the insight still in the list
        await page.goto('/saved_insights')
        await expect(page.locator('.saved-insights')).toContainText(insightName)
    })

    // test that was skip: "can delete dashboard and delete the insights" - might or might not be relevant
})
