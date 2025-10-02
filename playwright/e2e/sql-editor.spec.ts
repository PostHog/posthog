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
})
