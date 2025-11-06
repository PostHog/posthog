import { expect, test } from '../utils/playwright-test-base'

test.describe('SQL Editor', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('sql-editor')
    })

    test('See SQL Editor', async ({ page }) => {
        await expect(page.locator('[data-attr=editor-scene]')).toBeVisible()
        await expect(page.locator('[data-attr=sql-editor-source-empty-state]')).toBeVisible()
        await expect(page.getByText('SQL query')).toBeVisible()
    })

    test('Add source link', async ({ page }) => {
        await page.locator('[data-attr=sql-editor-add-source]').click()
        await expect(page).toHaveURL(/.*\/data-warehouse\/new-source/)
    })

    test('Run query', async ({ page }) => {
        await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).toBeVisible()
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1')
        await page.locator('[data-attr=sql-editor-run-button]').click()

        // query run
        await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()
    })

    test('Save view', async ({ page }) => {
        // Wait for the query editor to be visible and ready
        await expect(page.locator('[data-attr=hogql-query-editor]')).toBeVisible()
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1')

        // Wait for save button to be enabled before clicking
        await expect(page.locator('[data-attr=sql-editor-save-view-button]')).toBeEnabled()
        await page.locator('[data-attr=sql-editor-save-view-button]').click()

        // Wait for the modal/dialog to appear and be ready
        const nameInput = page.locator('[data-attr=sql-editor-input-save-view-name]')
        await expect(nameInput).toBeVisible()

        // Use a unique name to avoid conflicts with retries
        const uniqueViewName = `test_view_${Date.now()}`
        await nameInput.fill(uniqueViewName)

        // Wait for the Submit button to be enabled (form validation may need time)
        const submitButton = page.getByRole('button', { name: 'Submit' })
        await expect(submitButton).toBeEnabled()

        // Click submit
        await submitButton.click()

        // Wait for the success message which confirms the API call completed
        await expect(page.getByText(`${uniqueViewName} successfully created`)).toBeVisible()
        await expect(page.getByText(`Editing view "${uniqueViewName}"`)).toBeVisible()
    })

    test('Materialize view pane', async ({ page }) => {
        await page.getByText('Materialization').click()
        await expect(page.locator('[data-attr=sql-editor-sidebar-query-info-pane]')).toBeVisible()
    })

    test('Query variables pane', async ({ page }) => {
        await page.getByText('Variables').click()
        await expect(page.locator('[data-attr=sql-editor-sidebar-query-variables-pane]')).toBeVisible()
    })
})
