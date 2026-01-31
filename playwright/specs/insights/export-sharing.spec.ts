import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Export and Sharing', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('export chart data as CSV', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
        })

        await test.step('click Export button and download CSV', async () => {
            const exportButton = page.getByTestId('export-button')
            await exportButton.click()

            const downloadPromise = page.waitForEvent('download')
            await page.getByTestId('export-button-csv').click()
            const download = await downloadPromise
            expect(download.suggestedFilename()).toMatch(/\.csv$/i)
        })
    })

    test('export chart data as XLSX', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
        })

        await test.step('click Export button and download XLSX', async () => {
            const exportButton = page.getByTestId('export-button')
            await exportButton.click()

            const downloadPromise = page.waitForEvent('download')
            await page.getByTestId('export-button-xlsx').click()
            const download = await downloadPromise
            expect(download.suggestedFilename()).toMatch(/\.xlsx$/i)
        })
    })

    test('share insight URL', async ({ page }) => {
        const insight = new InsightPage(page)
        let savedUrl: string

        await test.step('create and save a Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Shared Insight')
            await insight.save()
            savedUrl = page.url()
            expect(savedUrl).not.toContain('/new')
        })

        await test.step('navigate away from the insight', async () => {
            await insight.goToList()
        })

        await test.step('navigate back to the saved URL and verify', async () => {
            await page.goto(savedUrl)
            await insight.trends.waitForChart()
            await expect(insight.topBarName).toContainText('Shared Insight')
            await expect(insight.trends.chart).toBeVisible()
        })
    })
})
