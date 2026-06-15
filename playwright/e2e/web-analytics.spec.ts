import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Web Analytics', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Can open add authorized URL form', async ({ page }) => {
        await page.goto('/web')
        // Open the domain filter dropdown
        await page.getByText('All domains').click()
        // Click the add button in the dropdown footer
        await page.getByText('Add authorized URL').click()
        await expect(page.locator('[data-attr="web-authorized-url-input"]')).toBeVisible()
    })
})
