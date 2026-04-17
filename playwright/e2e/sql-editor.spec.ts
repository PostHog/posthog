import { expect, test } from '../utils/playwright-test-base'

async function waitForSavedViewState(page: import('@playwright/test').Page, viewName: string): Promise<void> {
    await expect(async () => {
        const sceneTitle = page.locator('.scene-name h1 span').getByText(viewName, { exact: true })
        if (!(await sceneTitle.isVisible().catch(() => false))) {
            const savedViewRow = page.getByText(viewName, { exact: true }).last()
            await expect(savedViewRow).toBeVisible()
            await savedViewRow.click()
        }

        await expect(sceneTitle).toBeVisible()
        await expect(page.locator('[data-attr=sql-editor-materialization-button]')).toBeVisible()
    }).toPass({ timeout: 40000 })
}

async function openSaveAsViewModal(page: import('@playwright/test').Page): Promise<void> {
    await expect(async () => {
        await expect(page.locator('[data-attr=sql-editor-save-options-button]')).toBeEnabled()
        await page.locator('[data-attr=sql-editor-save-options-button]').click()

        const saveAsViewOption = page.getByRole('menuitem', { name: 'Save as view' })
        await expect(saveAsViewOption).toBeVisible()
        await saveAsViewOption.click()

        await expect(page.locator('[data-attr=sql-editor-input-save-view-name]')).toBeVisible()
    }).toPass({ timeout: 30000 })
}

test.describe('SQL Editor', () => {
    test.describe('Basic flow', () => {
        test.beforeEach(async ({ page }) => {
            await page.goToMenuItem('sql-editor')
        })

        test('See SQL Editor', async ({ page }) => {
            await expect(page.locator('[data-attr=editor-scene]')).toBeVisible()
            await expect(page.getByPlaceholder('Search warehouse')).toBeVisible()
            await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).toBeVisible()
            await expect(page.locator('.scene-name h1 span').getByText('New SQL query', { exact: true })).toBeVisible()
        })

        test('Add source link', async ({ page }) => {
            await page.locator('[data-attr=sql-editor-add-source]').click()
            await expect(page).toHaveURL(/.*\/data-warehouse\/new-source/)
        })

        test('Run query', async ({ page }) => {
            await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).toBeVisible()
            await page.locator('[data-attr=hogql-query-editor]').click()
            await page.locator('[data-attr=hogql-query-editor]').pressSequentially('SELECT 1')
            await page.locator('[data-attr=sql-editor-run-button]').click()

            // query run
            await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()
        })

        test('Save view', async ({ page }) => {
            test.slow()
            // Wait for the query editor to be visible and ready
            await expect(page.locator('[data-attr=hogql-query-editor]')).toBeVisible()
            await page.locator('[data-attr=hogql-query-editor]').click()
            await page.locator('[data-attr=hogql-query-editor]').pressSequentially('SELECT 1')
            await page.locator('[data-attr=sql-editor-run-button]').click()
            await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()

            // Open save options, then click save as view
            await openSaveAsViewModal(page)

            // Wait for the modal/dialog to appear and be ready
            const nameInput = page.locator('[data-attr=sql-editor-input-save-view-name]')

            // Use a unique name to avoid conflicts with retries
            const uniqueViewName = `test_view_${Date.now()}`
            await nameInput.fill(uniqueViewName)

            // Wait for the Submit button to be enabled (form validation may need time)
            const submitButton = page.getByRole('button', { name: 'Submit' })
            await expect(submitButton).toBeEnabled()

            // Click submit
            await submitButton.click()

            await waitForSavedViewState(page, uniqueViewName)
        })

        test('Materialize view pane', async ({ page }) => {
            test.slow()
            await expect(page.locator('[data-attr=hogql-query-editor]')).toBeVisible()
            await page.locator('[data-attr=hogql-query-editor]').click()
            await page.locator('[data-attr=hogql-query-editor]').pressSequentially('SELECT 1')
            await page.locator('[data-attr=sql-editor-run-button]').click()
            await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()

            await openSaveAsViewModal(page)

            const uniqueViewName = `materialized_test_view_${Date.now()}`
            const nameInput = page.locator('[data-attr=sql-editor-input-save-view-name]')
            await nameInput.fill(uniqueViewName)
            await page.getByRole('button', { name: 'Submit' }).click()
            await waitForSavedViewState(page, uniqueViewName)

            await page.locator('[data-attr=sql-editor-materialization-button]').click()
            await expect(page.locator('[data-attr=sql-editor-sidebar-query-info-pane]')).toBeVisible()
        })

        test('Query variables pane', async ({ page }) => {
            await page.getByText('Variables').click()
            await expect(page.locator('[data-attr=sql-editor-variables-button]')).toBeVisible()
        })
    })
})
