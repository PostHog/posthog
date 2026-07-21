import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Before Onboarding', () => {
    // Use a fresh workspace without demo data to exercise reaching settings pages on a new org/team.
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Navigate to a settings page even when a product has not been set up', async ({ page }) => {
        await page.goto('/settings/user')
        await expect(page.getByRole('heading', { level: 1 })).toContainText('Settings - Profile')

        await page.goto('/settings/organization')
        await expect(page.getByRole('heading', { level: 1 })).toContainText('Settings - General')
    })
})
