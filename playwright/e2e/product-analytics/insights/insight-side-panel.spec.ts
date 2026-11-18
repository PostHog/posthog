import { InsightPage } from '../../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

test.describe('Insight side panel actions', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('View source toggle enters edit mode and shows query editor', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create and save insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Side Panel Source Test')
            await insight.save()
            await insight.trends.waitForChart()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('open side panel and click view source', async () => {
            await insight.openInfoPanel()
            const viewSourceSwitch = page.getByTestId('insight-show-source')
            await expect(viewSourceSwitch).toBeVisible()
            await viewSourceSwitch.click()
        })

        await test.step('enters edit mode and shows query editor', async () => {
            await expect(insight.saveButton).toBeVisible()
            await expect(page.getByTestId('query-editor')).toBeVisible()
        })
    })
})
