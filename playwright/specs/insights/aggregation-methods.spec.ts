import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Aggregation Methods', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('Use Count per user aggregation with statistical options', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight page', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('click Total count to open aggregation dropdown', async () => {
            await page.getByRole('button', { name: 'Total count', exact: true }).click()
        })

        await test.step('select Count per user with median sub-option', async () => {
            // The Count per user menuitem has sub-option buttons (average, minimum, etc.)
            // Click the sub-option button first, then the menuitem closes with that selection
            const countPerUserItem = page.getByRole('menuitem', { name: /event count per user/ })
            await countPerUserItem.waitFor({ state: 'visible' })
            // Click the "median" button inside the menuitem to change the sub-option
            await countPerUserItem.getByRole('button').click()
            await page.getByRole('menuitem', { name: 'median' }).click()
        })

        await test.step('verify chart updates', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Use Property value aggregation', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight page', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('click Total count to open aggregation dropdown', async () => {
            await page.getByRole('button', { name: 'Total count', exact: true }).click()
        })

        await test.step('select Property value (auto-selects default property and sum)', async () => {
            const propertyValueItem = page.getByRole('menuitem', { name: /property value/ })
            await propertyValueItem.waitFor({ state: 'visible' })
            // Click the sub-option button to open stat type dropdown, then select sum
            await propertyValueItem.getByRole('button').click()
            await page.getByRole('menuitem', { name: 'sum' }).click()
        })

        await test.step('verify chart updates', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Test Weekly active users and Monthly active users', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight page', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('click Total count and select Weekly active users', async () => {
            await page.getByRole('button', { name: 'Total count', exact: true }).click()
            await page.getByRole('menuitem', { name: /Weekly active users/ }).click()
        })

        await test.step('verify chart updates for Weekly active users', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })

        await test.step('click aggregation again and select Monthly active users', async () => {
            await page
                .getByRole('button', { name: /Weekly active/ })
                .last()
                .click()
            await page.getByRole('menuitem', { name: /Monthly active users/ }).click()
        })

        await test.step('verify chart updates for Monthly active users', async () => {
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })
})
