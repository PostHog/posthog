import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Comparison Modes', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('enable comparison to previous period', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await expect(insight.trends.comparisonButton).toContainText('No comparison')
        })

        await test.step('select Compare to previous period', async () => {
            await insight.trends.comparisonButton.click()
            await page.getByText('Compare to previous period').click()
            await insight.trends.waitForChart()
            await expect(insight.trends.comparisonButton).toContainText('Previous period')
        })
    })

    test('disable comparison mode', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create insight with comparison enabled', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.comparisonButton.click()
            await page.getByText('Compare to previous period').click()
            await insight.trends.waitForChart()
            await expect(insight.trends.comparisonButton).toContainText('Previous period')
        })

        await test.step('disable comparison', async () => {
            await insight.trends.comparisonButton.click()
            await page.getByText('No comparison between periods').click()
            await insight.trends.waitForChart()
            await expect(insight.trends.comparisonButton).toContainText('No comparison')
        })
    })
})
