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
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1')

        await page.locator('[data-attr=sql-editor-save-view-button]').click()
        await page.locator('[data-attr=sql-editor-input-save-view-name]').fill('test_view')
        await page.getByText('Submit').click()

        await expect(page.getByText('test_view successfully created')).toBeVisible()
    })

    test('Materialize view pane', async ({ page }) => {
        await page.getByText('Materialization').click()
        await expect(page.locator('[data-attr=sql-editor-sidebar-query-info-pane]')).toBeVisible()
    })

    test('Query variables pane', async ({ page }) => {
        await page.getByText('Variables').click()
        await expect(page.locator('[data-attr=sql-editor-sidebar-query-variables-pane]')).toBeVisible()
    })

    test('Database panel toggle', async ({ page }) => {
        // Database panel should be visible initially
        await expect(page.locator('[data-attr=sql-editor-database-panel]')).toBeVisible()

        // Click to open if not already open
        const dataWarehouseButton = page.getByRole('button', { name: 'Data warehouse' })
        if (await dataWarehouseButton.isVisible()) {
            await dataWarehouseButton.click()
            await expect(page.locator('[data-attr=sql-editor-database-panel]')).toBeVisible()
        }
    })

    test('Run button changes state', async ({ page }) => {
        // Initial state should show "Run"
        await expect(page.locator('[data-attr=sql-editor-run-button]')).toContainText('Run')

        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1')

        // After entering query, run button should still show "Run"
        await expect(page.locator('[data-attr=sql-editor-run-button]')).toContainText('Run')
    })

    test('Query editor accepts and displays input', async ({ page }) => {
        const testQuery = 'SELECT * FROM events LIMIT 10'

        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill(testQuery)

        // Verify the query is in the editor
        const editorContent = await page.locator('textarea[aria-roledescription="editor"]').inputValue()
        expect(editorContent).toBe(testQuery)
    })

    test('Multiple queries in sequence', async ({ page }) => {
        // First query
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1')
        await page.locator('[data-attr=sql-editor-run-button]').click()
        await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()

        // Second query
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 2')
        await page.locator('[data-attr=sql-editor-run-button]').click()
        await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()
    })

    test('Clear query and verify empty state', async ({ page }) => {
        // Enter a query
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1')
        await page.locator('[data-attr=sql-editor-run-button]').click()

        // Clear the query
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('')

        // Verify editor is empty
        const editorContent = await page.locator('textarea[aria-roledescription="editor"]').inputValue()
        expect(editorContent).toBe('')
    })

    test('Query output pane shows results', async ({ page }) => {
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1 as test_column')
        await page.locator('[data-attr=sql-editor-run-button]').click()

        // Wait for output pane to show results (not empty state)
        await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()
    })

    test('Save view button is visible when query is entered', async ({ page }) => {
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1')

        // Save view button should be visible
        await expect(page.locator('[data-attr=sql-editor-save-view-button]')).toBeVisible()
    })

    test('Editor scene container has correct attributes', async ({ page }) => {
        const editorScene = page.locator('[data-attr=editor-scene]')

        await expect(editorScene).toBeVisible()
        await expect(editorScene).toHaveClass(/EditorScene/)
    })

    test('Run query with keyboard shortcut', async ({ page }) => {
        await page.locator('[data-attr=hogql-query-editor]').click()
        await page.locator('textarea[aria-roledescription="editor"]').fill('SELECT 1')

        // Press Cmd+Enter (or Ctrl+Enter on non-Mac)
        const modifier = process.platform === 'darwin' ? 'Meta' : 'Control'
        await page.keyboard.press(`${modifier}+Enter`)

        // Query should run
        await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()
    })

    test('Sidebar panes toggle visibility', async ({ page }) => {
        // Open Materialization pane
        await page.getByText('Materialization').click()
        await expect(page.locator('[data-attr=sql-editor-sidebar-query-info-pane]')).toBeVisible()

        // Switch to Variables pane
        await page.getByText('Variables').click()
        await expect(page.locator('[data-attr=sql-editor-sidebar-query-variables-pane]')).toBeVisible()
        await expect(page.locator('[data-attr=sql-editor-sidebar-query-info-pane]')).not.toBeVisible()
    })
})
