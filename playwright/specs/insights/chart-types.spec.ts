import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Chart Types', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('change chart type to Bar chart', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await expect(page.getByText('Line chart')).toBeVisible()
        })

        await test.step('select Bar chart', async () => {
            await insight.trends.chartTypeButton.click()
            await page.getByRole('menuitem', { name: /^Bar chart Trends over time/ }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('Bar chart')
        })
    })

    test('display data as a Number', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('select Number chart type', async () => {
            await insight.trends.chartTypeButton.click()
            await page.getByRole('menuitem', { name: /^Number/ }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('Number')
        })
    })

    test('use Pie chart visualization with breakdown', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight with breakdown', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
        })

        await test.step('select Pie chart', async () => {
            await insight.trends.chartTypeButton.click()
            await page.getByRole('menuitem', { name: /^Pie chart/ }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('Pie chart')
        })
    })
})
