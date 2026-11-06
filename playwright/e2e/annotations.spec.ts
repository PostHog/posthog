import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Annotations', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
        await page.goToMenuItem('datamanagement')
        await page.goToMenuItem('annotations')
    })

    test('Create annotation', async ({ page }) => {
        // Wait for the create button to be visible before clicking
        const createButton = page.getByTestId('create-annotation')
        await expect(createButton).toBeVisible()
        await createButton.click()

        // Use a unique name to avoid conflicts with retries
        const uniqueAnnotationName = `Test Annotation ${Date.now()}`
        await page.fill('[data-attr=create-annotation-input]', uniqueAnnotationName)
        await page.click('[data-attr=create-annotation-submit]')
        await expect(page.locator('[data-attr=annotations-table]')).toContainText(uniqueAnnotationName)
    })
})
