import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Date Range and Interval', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('change date range to Last 30 days', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await expect(page.getByText('Last 7 days')).toBeVisible()
        })

        await test.step('open date range picker and select Last 30 days', async () => {
            await insight.trends.dateRangeButton.click()
            await page.getByText('Last 30 days').click()
            await insight.trends.waitForChart()
            await expect(insight.trends.dateRangeButton).toContainText('Last 30 days')
        })
    })

    test('change interval from day to week', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight with Last 90 days', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.dateRangeButton.click()
            await page.getByText('Last 90 days').click()
            await insight.trends.waitForChart()
        })

        await test.step('change interval to week', async () => {
            await page.getByText('grouped by').locator('..').getByRole('button').first().click()
            await page.getByRole('menuitem', { name: 'week' }).click()
            await insight.trends.waitForChart()
            await expect(page.getByText('grouped by')).toBeVisible()
        })
    })
})
