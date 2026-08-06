import { delay } from 'lib/utils/async'

import { randomString } from '../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Early Access Management', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
        await page.goto('/early_access_features')
    })

    test('Early access feature new and list', async ({ page }) => {
        // load an empty early access feature page
        await expect(page.locator('h1')).toContainText('Early access features')
        await expect(page).toHaveTitle('Early access features • PostHog')

        // go to create a new feature
        await page.getByRole('link', { name: 'New feature' }).click()

        // cancel new feature
        await page.locator('[data-attr="cancel-feature"]').click()
        await expect(page.locator('h1')).toContainText('Early access features')

        const name = randomString('test-feature')

        // set feature name & description
        await page.getByRole('link', { name: 'New feature' }).click()
        await page.click('[data-attr="scene-title-textarea"]')
        await page.locator('[data-attr="scene-title-textarea"]').pressSequentially(name)
        await delay(1000)
        await expect(page.locator('[data-attr="save-feature"]')).toContainText('Save as draft')

        // save
        await page.locator('[data-attr="save-feature"]').click()
        await expect(page.locator('[data-attr="success-toast"]')).toContainText('Early access feature saved')

        // back to features
        await page.goto('/early_access_features')
        await expect(page.locator('tbody')).toContainText(name)

        // edit feature — use the row link by role and confirm we actually navigated to the
        // feature detail before clicking Edit. The Edit button only renders once the feature
        // has loaded in view mode, so a click that didn't navigate would hang for the full
        // test timeout waiting for it.
        await page.getByRole('link', { name }).click()
        await expect(page).toHaveURL(/\/early_access_features\/[\w-]+$/)
        await page.locator('[data-attr="edit-feature"]').click()
        await expect(page.locator('[data-attr="scene-title-textarea"]')).toContainText(name)
        await expect(page.locator('[data-attr="save-feature"]')).toContainText('Save')

        // delete feature
        await page.locator('[data-attr="open-context-panel-button"]').first().click()
        await page.locator('[data-attr="early-access-feature-delete"]').click()
        await expect(page.getByRole('heading', { name: 'Permanently delete feature?' })).toBeVisible()
        await page.locator('[data-attr="confirm-delete-feature"]').click()
        await expect(page.locator('[data-attr=info-toast]')).toContainText(
            'Early access feature deleted. Remember to delete corresponding feature flag if necessary'
        )
    })
})
