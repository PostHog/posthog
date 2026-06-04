import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Before Onboarding', () => {
    // A fresh workspace has incomplete onboarding by default, so we don't skip it here —
    // this exercises reaching settings pages before any product is set up.
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
