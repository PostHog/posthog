import { DashboardPage } from '../../page-models/dashboardPage'
import { InsightPage } from '../../page-models/insightPage'
import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Dashboards', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Editing an insight updates the dashboard tile', async ({ page }) => {
        const insight = new InsightPage(page)
        const dashboard = new DashboardPage(page)
        const insightName = randomString('dash-insight')
        const updatedName = randomString('dash-updated')

        await test.step('create and save a Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('add the insight to a new dashboard', async () => {
            await dashboard.addInsightToNewDashboard()
            await expect(page.getByText(insightName)).toBeVisible()
        })

        await test.step('open the insight from dashboard tile', async () => {
            await page.locator('.InsightCard').getByText(insightName).click()
            await expect(page).toHaveURL(/\/insights\//)
        })

        await test.step('edit the insight name', async () => {
            await insight.edit()
            await insight.editName(updatedName)
            await insight.save()
            await expect(insight.topBarName).toContainText(updatedName)
        })

        await test.step('navigate back and verify the updated name on the dashboard', async () => {
            await page.locator('a[href*="/dashboard/"]').first().click()
            await expect(page).toHaveURL(/\/dashboard\//)
            await expect(page.getByText(updatedName)).toBeVisible()
        })
    })

    test('Can duplicate, rename, and remove dashboard tiles', async ({ page }) => {
        const insight = new InsightPage(page)
        const dashboard = new DashboardPage(page)
        const insightName = randomString('tile-ops')
        const renamedTileName = randomString('tile-renamed')

        await test.step('create insight and add to dashboard', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
            await dashboard.addInsightToNewDashboard()
            await expect(page.locator('.InsightCard')).toHaveCount(1)
        })

        await test.step('duplicate the tile', async () => {
            await dashboard.closeSidePanels()
            await dashboard.duplicateFirstTile()
            await expect(page.locator('.InsightCard')).toHaveCount(2)
        })

        await test.step('rename the first tile', async () => {
            await dashboard.renameFirstTile(renamedTileName)
            await expect(page.locator('.InsightCard').first().getByText(renamedTileName)).toBeVisible()
        })

        await test.step('remove the first tile', async () => {
            await dashboard.removeFirstTile()
            await expect(page.locator('.InsightCard')).toHaveCount(1)
        })
    })
})
