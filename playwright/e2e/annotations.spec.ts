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

    test('Annotations loaded', async ({ page }) => {
        // Check that the annotations page loaded with key elements visible.
        // Scope to the scene title, a bare 'Annotations' heading match also hits the
        // empty-state "Welcome to Annotations!" h2 (substring match) and trips strict mode.
        await expect(page.getByTestId('scene-name').getByRole('heading', { name: 'Annotations' })).toBeVisible()
        // The setup empty state replaces the table until the first annotation exists, and
        // both render a create button under this data-attr. Assert the attr rather than the
        // label so the check holds whichever of the two the project is currently showing.
        await expect(page.getByTestId('create-annotation')).toBeVisible()
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
