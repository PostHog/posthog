import { InsightType } from '~/types'

import { InsightPage } from '../../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

test.describe('Lifecycle insights', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('verify chart and lifecycle toggles, save and persist', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Lifecycle insight and wait for result', async () => {
            await insight.goToNewInsight(InsightType.LIFECYCLE)
            await expect(insight.activeTab).toContainText('Lifecycle')
            await insight.lifecycle.waitForChart()
        })

        await test.step('verify lifecycle toggles section is present', async () => {
            await expect(page.getByText('Lifecycle Toggles')).toBeVisible()
        })

        await test.step('save and verify view mode', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })
    })
})
