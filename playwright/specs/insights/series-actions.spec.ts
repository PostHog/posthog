import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Series Actions', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('add filters to a specific series', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('add a global property filter (Browser)', async () => {
            // Use the global "Add filter group" button in the Filters section
            await page.getByRole('button', { name: 'Add filter group' }).click()
            // Click the "+ Filter" button inside the new filter group to open the taxonomic popup
            await page.getByRole('button', { name: 'Filter', exact: true }).click()
            const searchField = page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible' })
            await searchField.fill('Browser')
            await page.locator('.taxonomic-list-row').first().click()
        })

        await test.step('verify chart updates', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('duplicate a series', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('click the three-dot menu on first series and duplicate', async () => {
            await insight.trends.firstSeries.hover()
            await page.getByRole('button', { name: 'Show more actions', exact: true }).first().click({ force: true })
            await page.getByTestId('show-prop-duplicate-0').click()
        })

        await test.step('verify second series appears', async () => {
            await expect(insight.trends.secondSeries).toBeVisible()
        })
    })

    test('reorder series via duplicate and delete', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight and add second series', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.addSeries()
            await insight.trends.selectEvent(1, 'Pageleave')
            await insight.trends.waitForChart()
        })

        await test.step('verify initial order', async () => {
            await expect(insight.trends.firstSeries).toContainText('Pageview')
            await expect(insight.trends.secondSeries).toContainText('Pageleave')
        })

        await test.step('delete the first series to change order', async () => {
            // Open the three-dot menu on the first series and delete it
            await insight.trends.firstSeries.hover()
            await page.getByRole('button', { name: 'Show more actions', exact: true }).first().click({ force: true })
            await page.getByRole('button', { name: 'Delete' }).click()
        })

        await test.step('verify Pageleave is now the only series', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.firstSeries).toContainText('Pageleave')
        })
    })
})
