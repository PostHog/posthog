import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Chart Types Advanced', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('Use Area chart and Stacked bar chart', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new trends insight with two series', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.addSeries()
        })

        await test.step('select Area chart type', async () => {
            await insight.trends.chartTypeButton.click()
            await page.getByRole('menuitem', { name: /^Area chart/ }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('Area chart')
        })

        await test.step('select Stacked bar chart type', async () => {
            await insight.trends.chartTypeButton.click()
            await page.getByRole('menuitem', { name: /^Stacked bar chart/ }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('Stacked bar chart')
        })
    })

    test('Use cumulative line chart', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('select cumulative line chart type', async () => {
            await insight.trends.chartTypeButton.click()
            await page.getByRole('menuitem', { name: /^Line chart \(cumulative\)/ }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('Line chart (cumulative)')
        })
    })

    test('Display data in Table view', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('select Table chart type', async () => {
            await insight.trends.chartTypeButton.click()
            await page.getByRole('menuitem', { name: /^Table/ }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('Table')
        })
    })

    test('Use World map with country breakdown', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('add breakdown by Country code', async () => {
            await insight.trends.addBreakdown('Country code')
            await insight.trends.waitForChart()
        })

        await test.step('select World map chart type', async () => {
            await insight.trends.chartTypeButton.click()
            const worldMapItem = page.getByRole('menuitem', { name: /Visualize data by country/ })
            await worldMapItem.scrollIntoViewIfNeeded()
            await worldMapItem.click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('World map')
        })
    })
})
