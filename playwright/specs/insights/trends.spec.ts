import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Trends insights', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('create new insight with default settings', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to Product analytics and verify insights list', async () => {
            await insight.goToList()
            await expect(page.locator('table')).toBeVisible()
        })

        await test.step('click New to create a Trends insight', async () => {
            await page.getByTestId('saved-insights-new-insight-button').click()
            await expect(insight.activeTab).toContainText('Trends')
            await expect(insight.trends.firstSeries).toBeVisible()
            await insight.trends.waitForChart()
            await expect(page.getByText('Detailed results')).toBeVisible()
        })

        await test.step('verify default configuration', async () => {
            await expect(insight.trends.firstSeries).toHaveText('Pageview')
            await expect(page.getByText('Total count')).toBeVisible()
            await expect(page.getByText('Last 7 days')).toBeVisible()
            await expect(page.getByText('Line chart')).toBeVisible()
            await expect(page.getByText('No comparison')).toBeVisible()
            await expect(insight.trends.breakdownButton).toBeVisible()
        })
    })

    test('save insight with custom name', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('set a custom name and save', async () => {
            await insight.editName('Weekly User Activity')
            await insight.save()
            await expect(insight.editButton).toBeVisible()
            expect(page.url()).not.toContain('/new')
        })

        await test.step('verify insight appears in the list', async () => {
            await insight.goToList()
            await expect(page.getByText('Weekly User Activity')).toBeVisible()
        })
    })

    test('change event selection in a series', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await expect(insight.trends.firstSeries).toBeVisible()
        })

        await test.step('select a different event', async () => {
            await insight.trends.selectEvent(0, 'downloaded_file')
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
            await expect(insight.trends.detailsTable.getByText('downloaded_file')).toBeVisible()
        })
    })

    test('add a second series', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await expect(insight.trends.firstSeries).toBeVisible()
        })

        await test.step('add second series and change its event', async () => {
            await insight.trends.addSeries()
            await expect(insight.trends.secondSeries).toBeVisible()
            await insight.trends.selectEvent(1, 'downloaded_file')
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
            await expect(insight.trends.detailsLabels).toHaveCount(2)
            await expect(insight.trends.detailsLabels.nth(0)).toContainText('Pageview')
            await expect(insight.trends.detailsLabels.nth(1)).toContainText('downloaded_file')
        })
    })

    test('enable and use formula mode', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a Trends insight with two series', async () => {
            await insight.goToNewTrends()
            await insight.trends.addSeries()
            await expect(insight.trends.secondSeries).toBeVisible()
        })

        await test.step('enable formula mode and enter a formula', async () => {
            await insight.trends.setFormula('A + B')
            await expect(insight.trends.formulaInput.first()).toHaveValue('A + B')
            await insight.trends.waitForChart()
            await expect(insight.trends.detailsTable).toBeVisible()
        })

        await test.step('disable formula mode', async () => {
            await insight.trends.formulaSwitch.click()
            await expect(insight.trends.formulaInput).not.toBeVisible()
            await expect(insight.trends.firstSeries).toBeVisible()
            await expect(insight.trends.secondSeries).toBeVisible()
        })
    })

    test('add a property breakdown by browser', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('add breakdown by Browser', async () => {
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
            const rowCount = await insight.trends.detailsLabels.count()
            expect(rowCount).toBeGreaterThanOrEqual(1)
        })
    })
})
