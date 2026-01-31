import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Edge Cases', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('create insight with no data for selected event', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('select an event that has no data', async () => {
            await insight.trends.seriesEventButton(0).click()
            const searchField = page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible' })
            await searchField.fill('nonexistent_event_xyz')
            await page.keyboard.press('Escape')
        })

        await test.step('verify chart displays gracefully with no data', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('create insight with date range in the future', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('select a far future date range using calendar', async () => {
            await insight.trends.dateRangeButton.click()
            await page.getByText('Custom fixed date range').click()

            // Click next month several times to get to a future month
            for (let i = 0; i < 6; i++) {
                await page
                    .locator('[data-attr="lemon-calendar-range-with-time"]')
                    .locator('button:has(svg)')
                    .last()
                    .click()
                await page.waitForTimeout(200)
            }

            // Select day 1 as start
            await page.locator('.LemonCalendar').getByRole('button', { name: '1', exact: true }).first().click()
            // Select day 15 as end
            await page.getByRole('button', { name: /End:/ }).click()
            await page.locator('.LemonCalendar').getByRole('button', { name: '15', exact: true }).first().click()
            // Apply
            await page.getByRole('button', { name: 'Apply' }).click()
        })

        await test.step('verify chart shows no data without crashing', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('apply contradictory filters', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('add a filter: Browser property', async () => {
            // Use the global "Add filter group" button in the Filters section
            await page.getByRole('button', { name: 'Add filter group' }).click()
            // Click the "+ Filter" button inside the new filter group
            await page.getByRole('button', { name: 'Filter', exact: true }).click()
            const searchField = page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible' })
            await searchField.fill('Browser')
            await page.locator('.taxonomic-list-row').first().click()
        })

        await test.step('verify chart still displays', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('use All time date range', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('click date range button', async () => {
            await insight.trends.dateRangeButton.click()
        })

        await test.step('select All time option', async () => {
            await page.getByText('All time', { exact: true }).click()
        })

        await test.step('verify chart loads without crashing', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
            await expect(insight.trends.dateRangeButton).toContainText('All time')
        })
    })

    test('create insight with high cardinality breakdown', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('add breakdown by high-cardinality property', async () => {
            await insight.trends.addBreakdown('$session_id')
        })

        await test.step('verify chart handles it gracefully', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })
})
