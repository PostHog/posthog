import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('System Status', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true, staff: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('System Status loaded', async ({ page }) => {
        await page.locator('[data-attr=help-menu-button]').click()
        await page.locator('[data-attr=help-menu-admin-button]').click()
        await page.locator('[data-attr=help-menu-instance-panel-button]').click()
        await expect(page.locator('table')).toHaveText(/Events in ClickHouse/)
    })
})
