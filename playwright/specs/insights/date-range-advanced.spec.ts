import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Advanced Date Range and Comparison', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('use custom fixed date range', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('open date picker and select fixed date range', async () => {
            await insight.trends.dateRangeButton.click()
            await page.getByText('Custom fixed date range').click()
        })

        await test.step('select start and end dates from calendar', async () => {
            // Click the "Start:" button (already selected by default), then pick a day
            await page.locator('.LemonCalendar').getByRole('button', { name: '1', exact: true }).first().click()
            // Click the "End:" button to switch to end date selection
            await page.getByRole('button', { name: /End:/ }).click()
            // Pick end day
            await page.locator('.LemonCalendar').getByRole('button', { name: '15', exact: true }).first().click()
            // Click Apply
            await page.getByRole('button', { name: 'Apply' }).click()
        })

        await test.step('verify chart updates with custom range', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('use rolling date range with custom value', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('open date picker and change the rolling value', async () => {
            await insight.trends.dateRangeButton.click()
            const numberInput = page.locator('input[type="number"]').first()
            await numberInput.fill('14')
            await numberInput.press('Enter')
        })

        await test.step('verify date range updates', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.dateRangeButton).toContainText('14')
        })
    })

    test('use minute and hour intervals', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('select Last 24 hours date range', async () => {
            await insight.trends.dateRangeButton.click()
            await page.getByText('Last 24 hours').click()
            await insight.trends.waitForChart()
        })

        await test.step('change interval to hour', async () => {
            await page.locator('[data-attr="interval-filter"]').click()
            await page.getByRole('menuitem', { name: 'hour' }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('use custom comparison period', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('enable comparison to previous period', async () => {
            await insight.trends.comparisonButton.click()
            await page.getByText('Compare to previous period').click()
            await insight.trends.waitForChart()
            await expect(insight.trends.comparisonButton).toContainText('Previous period')
        })
    })
})
