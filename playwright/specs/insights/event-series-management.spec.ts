import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Event and Series Management', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null
    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })
    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('Search for an event in the event selector', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('Click first series to open selector', async () => {
            await insight.trends.firstSeries.click()
        })

        await test.step('Type "file" in search field and verify filtered results', async () => {
            await page.getByTestId('taxonomic-filter-searchfield').fill('file')
            await expect(page.locator('.taxonomic-list-row').first()).toBeVisible()
        })

        await test.step('Click first row and verify chart updates', async () => {
            await page.locator('.taxonomic-list-row').first().click()
            await insight.trends.waitForChart()
        })
    })

    test('Select an Action instead of an Event', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('Click first series to open selector', async () => {
            await insight.trends.firstSeries.click()
        })

        await test.step('Click Actions category', async () => {
            await page
                .getByText('Actions', { exact: false })
                .filter({ hasText: /Actions/ })
                .first()
                .click()
        })

        await test.step('Select first action row', async () => {
            await page.locator('.taxonomic-list-row').first().click()
        })

        await test.step('Verify chart updates', async () => {
            await insight.trends.waitForChart()
        })
    })

    test('Remove a series', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight and add series', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.addSeries()
            await expect(insight.trends.secondSeries).toBeVisible()
        })

        await test.step('Click three dot menu and delete second series', async () => {
            await page.getByRole('button', { name: 'Show more actions' }).nth(1).click({ force: true })
            await page.getByRole('button', { name: 'Delete' }).click()
        })

        await test.step('Verify second series removed', async () => {
            await expect(insight.trends.secondSeries).not.toBeVisible()
            await expect(insight.trends.firstSeries).toBeVisible()
        })
    })
})
