// spec: specs/trends-insights.plan.md
// seed: seed.spec.ts
import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Aggregation Methods', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('Change aggregation to Unique users', async ({ page }) => {
        const insight = new InsightPage(page)

        // 1. Navigate to new Trends insight page at /insights/new
        await test.step('navigate to new Trends insight page', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await expect(insight.activeTab).toContainText('Trends')
            await expect(page.getByText('Total count').first()).toBeVisible()
        })

        // 2. Click on the 'Total count' aggregation button
        await test.step('click on Total count aggregation button', async () => {
            await page.getByText('Total count').first().click()
            await expect(page.getByText('Unique users')).toBeVisible()
        })

        // 3. Select 'Unique users'
        await test.step('select Unique users', async () => {
            await page.getByText('Unique users').click()
            await expect(page.getByText('Unique users').first()).toBeVisible()
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })
})
