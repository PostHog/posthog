import { InsightPage } from '../../page-models/insightPage'
import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Insights list', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Can create, search, and open an insight', async ({ page }) => {
        const insight = new InsightPage(page)
        const insightName = randomString('list-test')

        await test.step('create and save a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('search for the insight and navigate to it', async () => {
            await insight.goToList()
            await page.getByPlaceholder('Search').fill(insightName)

            // Wait for the table to settle with exactly one row containing our insight.
            // This avoids a race where the search API response arrives mid-click,
            // re-rendering the table and detaching the link element before navigation fires.
            const rows = page.locator('table tbody tr')
            await expect(rows).toHaveCount(1, { timeout: 10_000 })

            const link = rows.first().getByRole('link', { name: insightName })
            await expect(link).toBeVisible()
            await link.click()

            await expect(insight.topBarName).toContainText(insightName, { timeout: 15_000 })
        })
    })
})
