import { DashboardPage } from '../page-models/dashboardPage'
import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Duplicating dashboards', () => {
    let dashboardName: string
    let insightName: string
    let expectedCopiedDashboardName: string
    let expectedCopiedInsightName: string

    test.beforeEach(async ({ page }) => {
        dashboardName = randomString('dashboard-')
        expectedCopiedDashboardName = `${dashboardName} (Copy)`
        insightName = randomString('insight-')
        expectedCopiedInsightName = `${insightName} (Copy)`

        await page.goto('/saved_insights')
        await page.goToMenuItem('dashboards')

        // create empty dash
        const dashPage = new DashboardPage(page)
        await dashPage.createNew(dashboardName)

        // add an insight
        await page.locator('[data-attr="dashboard-add-graph-header"]').getByText('Add insight').click()
        await page.locator('[data-attr="dashboard-add-new-insight"]').getByText('New insight').click()
        await page.fill('[data-attr="top-bar-name"] input', insightName)
        await page.click('[data-attr="top-bar-name"] button:has-text("Save")')
        await page.click('[data-attr=insight-save-button]:has-text("Save & add to dashboard")')
        await expect(page.locator('.CardMeta h4')).toContainText(insightName)
    })

    test('can duplicate a dashboard without duplicating insights, from dashboard list', async ({ page }) => {
        await page.goToMenuItem('dashboards')
        await page.fill('[placeholder="Search for dashboards"]', dashboardName)

        const row = page.locator('[data-attr="dashboards-table"] tr', { hasText: dashboardName })
        await row.locator('[data-attr="more-button"]').click()
        await page.locator('li:has-text("Duplicate dashboard")').click()
        // no "duplicate tiles" selected
        await page.locator('[data-attr="dashboard-submit-and-go"]').click()

        await expect(page.locator('[data-attr="top-bar-name"] .EditableField__display')).toHaveText(
            expectedCopiedDashboardName
        )

        // should not have "(Copy)" on the tile itself
        await expect(page.locator('.CardMeta h4')).toContainText(insightName)
    })

    test('can duplicate a dashboard AND duplicate insights, from the dashboard list', async ({ page }) => {
        await page.goToMenuItem('dashboards')
        await page.fill('[placeholder="Search for dashboards"]', dashboardName)

        const row = page.locator('[data-attr="dashboards-table"] tr', { hasText: dashboardName })
        await row.locator('[data-attr="more-button"]').click()
        await page.locator('li:has-text("Duplicate dashboard")').click()
        await page.click('span', { hasText: "Duplicate this dashboard's tiles" })
        await page.locator('[data-attr="dashboard-submit-and-go"]').click()

        await expect(page.locator('[data-attr="top-bar-name"] .EditableField__display')).toHaveText(
            expectedCopiedDashboardName
        )
        await expect(page.locator('.CardMeta h4')).toContainText(expectedCopiedInsightName)
    })
})
