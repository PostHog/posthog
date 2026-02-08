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

    test('Can create a new dashboard with an insight', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const dashboardName = randomString('dash-edit')

        await test.step('create a dashboard', async () => {
            await dashboard.createNew(dashboardName)
        })

        await test.step('add the insight to the dashboard', async () => {
            await dashboard.addInsightToNewDashboard()
            await expect(page.locator('.InsightCard')).toBeVisible()
        })
    })

    test('Editing an insight updates the dashboard tile', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const insight = new InsightPage(page)
        const updatedName = randomString('dash-updated')

        await test.step('create a dashboard with an insight', async () => {
            await dashboard.createNew()
            await dashboard.addInsightToNewDashboard()
            await expect(page.locator('.InsightCard')).toBeVisible()
        })

        await test.step('select to edit an insight', async () => {
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Edit')
            await expect(page).toHaveURL(/edit/)
        })

        await test.step('edit the insight name', async () => {
            await insight.editName(updatedName)
            await expect(insight.topBarName).toContainText(updatedName)
        })

        await test.step('navigate back and verify the updated insight on the dashboard', async () => {
            await page.goBack()

            await expect(page).toHaveURL(/\/dashboard\//)
            await expect(page.getByText(updatedName)).toBeVisible()
        })
    })

    test('Add insight to new dashboard and view it there', async ({ page }) => {
        const insight = new InsightPage(page)
        const dashboard = new DashboardPage(page)
        const insightName = randomString('add-to-dash')

        await test.step('create and save a Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('add insight to a new dashboard', async () => {
            await dashboard.addToNewDashboardFromInsightPage()
        })

        await test.step('verify insight is visible on the new dashboard', async () => {
            await expect(page).toHaveURL(/\/dashboard\//)
            const card = page.locator('.InsightCard').filter({ hasText: insightName })
            await expect(card).toBeVisible()
            await expect(card.locator('canvas')).toBeVisible()
        })
    })

    test('Can duplicate, rename, and remove dashboard tiles', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const newTileName = randomString('tile-name')

        await test.step('create a dashboard with an insight', async () => {
            await dashboard.createNew()
            await dashboard.addInsightToNewDashboard()
            await expect(page.locator('.InsightCard')).toBeVisible()
        })

        await test.step('duplicate the tile', async () => {
            const titleLocator = page.locator('.InsightCard').first().getByTestId('insight-card-title')
            await expect(titleLocator).not.toContainText('Loading')
            const title = await titleLocator.textContent()
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Duplicate')

            const duplicateTile = page.getByText(`${title} (Copy)`)
            await duplicateTile.scrollIntoViewIfNeeded()
            await expect(duplicateTile).toBeVisible()
        })

        await test.step('rename the first tile', async () => {
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Rename')

            const renameModal = page.locator('.LemonModal').filter({ has: page.getByTestId('insight-name') })
            await renameModal.getByTestId('insight-name').fill(newTileName)
            await renameModal.getByText('Submit').click()

            await expect(page.locator('.InsightCard').first().getByText(newTileName)).toBeVisible()
        })

        await test.step('remove the first tile', async () => {
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Remove from dashboard')

            await expect(page.locator('.InsightCard').first().getByText(newTileName)).not.toBeVisible()
        })
    })
})
