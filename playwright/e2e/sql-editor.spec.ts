import { expect, test } from '../utils/workspace-test-base'
import type { PlaywrightWorkspaceSetupResult } from '../utils/workspace-test-base'

async function waitForSavedViewState(page: import('@playwright/test').Page): Promise<void> {
    await expect(page.getByTestId('sql-editor-input-save-view-name')).toHaveCount(0, { timeout: 40000 })
    await expect(page.getByTestId('sql-editor-save-options-button')).toHaveCount(0, { timeout: 40000 })
    await expect(page.getByRole('button', { name: 'Update view' })).toBeVisible({ timeout: 40000 })
    await expect(page.getByTestId('sql-editor-materialization-button')).toBeVisible({ timeout: 40000 })
}

async function openSaveAsViewModal(page: import('@playwright/test').Page): Promise<void> {
    const saveOptionsButton = page.getByTestId('sql-editor-save-options-button')
    await expect(saveOptionsButton).toBeEnabled({ timeout: 30000 })
    await saveOptionsButton.click()

    const saveAsViewOption = page.getByRole('menuitem', { name: 'Save as view' })
    await expect(saveAsViewOption).toBeVisible()
    await saveAsViewOption.click()

    await expect(page.getByTestId('sql-editor-input-save-view-name')).toBeVisible()
}

async function runBasicQuery(page: import('@playwright/test').Page): Promise<void> {
    const queryEditor = page.getByTestId('hogql-query-editor')
    await expect(queryEditor).toBeVisible()
    await queryEditor.click()
    await queryEditor.pressSequentially('SELECT 1')
    await page.getByTestId('sql-editor-run-button').click()

    await expect(page.getByTestId('sql-editor-output-pane-empty-state')).not.toBeVisible()
}

async function saveView(page: import('@playwright/test').Page, viewName: string): Promise<void> {
    await openSaveAsViewModal(page)

    const nameInput = page.getByTestId('sql-editor-input-save-view-name')
    await nameInput.fill(viewName)

    await page.getByRole('button', { name: 'Submit' }).click()
    await waitForSavedViewState(page)
}

test.describe('SQL Editor', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            skip_onboarding: true,
            no_demo_data: true,
        })
    })

    test.describe('Basic flow', () => {
        test.beforeEach(async ({ page, playwrightSetup }) => {
            await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
            await page.goToMenuItem('sql-editor')
        })

        test('See SQL Editor', async ({ page }) => {
            await expect(page.getByTestId('editor-scene')).toBeVisible()
            await expect(page.getByPlaceholder('Search warehouse')).toBeVisible()
            await expect(page.getByTestId('sql-editor-output-pane-empty-state')).toBeVisible()
            await expect(page.getByTestId('scene-name')).toContainText('New SQL query')
        })

        test('Add source link', async ({ page }) => {
            await page.getByTestId('sql-editor-add-source').click()
            await expect(page).toHaveURL(/.*\/data-warehouse\/new-source/)
        })

        test('Run query', async ({ page }) => {
            await expect(page.getByTestId('sql-editor-output-pane-empty-state')).toBeVisible()
            await runBasicQuery(page)
        })

        test('Save view', async ({ page }) => {
            test.slow()
            const uniqueViewName = `test_view_${Date.now()}`
            await runBasicQuery(page)
            await saveView(page, uniqueViewName)
        })

        test('Materialize view pane', async ({ page }) => {
            test.slow()
            const uniqueViewName = `materialized_test_view_${Date.now()}`
            await runBasicQuery(page)
            await saveView(page, uniqueViewName)

            await page.getByTestId('sql-editor-materialization-button').click()
            await expect(page.getByTestId('sql-editor-sidebar-query-info-pane')).toBeVisible()
        })

        test('Query variables pane', async ({ page }) => {
            await page.getByText('Variables').click()
            await expect(page.getByTestId('sql-editor-variables-button')).toBeVisible()
        })
    })
})
