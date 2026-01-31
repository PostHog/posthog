import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Filters and Breakdowns', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('Search for a breakdown property', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight and wait for chart', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('Click breakdown button and search', async () => {
            await insight.trends.breakdownButton.click()
            const searchField = page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible' })
            await searchField.fill('country')
        })

        await test.step('Verify filtered results and select', async () => {
            await expect(page.locator('.taxonomic-list-row').first()).toBeVisible()
            await page.locator('.taxonomic-list-row').first().click()
            await insight.trends.waitForChart()
        })
    })

    test('Add breakdown by Person property', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight and wait for chart', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('Click breakdown button', async () => {
            await insight.trends.breakdownButton.click()
        })

        await test.step('Click Person properties category', async () => {
            await page
                .getByText(/Person properties/i)
                .first()
                .click()
        })

        await test.step('Select a person property', async () => {
            await page.locator('.taxonomic-list-row').first().click()
        })

        await test.step('Verify breakdown applied and chart updates', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Remove a breakdown', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight and add breakdown', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
        })

        await test.step('Remove breakdown via the close button on the tag', async () => {
            // The breakdown tag has a close (×) button to remove it
            const breakdownTag = page.locator('.BreakdownTag').first()
            await breakdownTag.hover()
            // Click the close/remove button (× icon) on the tag
            await breakdownTag.locator('[aria-label="close"]').or(breakdownTag.locator('button')).last().click()
        })

        await test.step('Verify chart returns to non-breakdown state', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Add a global filter group', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight and wait for chart', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('Add a global filter group', async () => {
            // Use the global "Add filter group" button in the Filters section
            await page.getByRole('button', { name: 'Add filter group' }).click()
            // Click the "+ Filter" button inside the new filter group to open the taxonomic popup
            await page.getByRole('button', { name: 'Filter', exact: true }).click()
            const searchField = page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible' })
            await searchField.fill('Browser')
            await page.locator('.taxonomic-list-row').first().click()
        })

        await test.step('Verify chart updates', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Toggle filter out internal and test users', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight and wait for chart', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('Toggle the filter out internal and test users switch', async () => {
            const filterSwitch = page.getByRole('switch', { name: 'Filter out internal and test users' })
            await filterSwitch.click()
        })

        await test.step('Verify chart updates', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Add multiple breakdown properties', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('Navigate to new Trends insight and wait for chart', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('Add first breakdown: Browser', async () => {
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
        })

        await test.step('Add second breakdown: OS', async () => {
            await insight.trends.breakdownButton.click()
            const searchField = page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible' })
            await searchField.fill('OS')
            await page.locator('.taxonomic-list-row').first().click()
            await insight.trends.waitForChart()
        })

        await test.step('Verify multiple breakdowns and chart visible', async () => {
            await expect(insight.trends.chart).toBeVisible()
            await expect(insight.trends.detailsLabels.first()).toBeVisible()
        })
    })
})
