import { Page } from '@playwright/test'

import { SqlInsight } from '../page-models/insights/sqlInsight'
import { expect, test, PlaywrightWorkspaceSetupResult } from '../utils/workspace-test-base'

async function dismissQuickStart(page: Page): Promise<void> {
    await page
        .getByRole('button', { name: 'Minimize' })
        .click({ timeout: 1000 })
        .catch(() => {})
}

async function goToSqlEditor(page: Page): Promise<void> {
    await page.goto('/sql')
    await expect(page).toHaveURL(/\/sql(?:[?#].*)?$/)
    await expect(page.getByTestId('editor-scene')).toBeVisible({ timeout: 60000 })
    await expect(page.getByTestId('hogql-query-editor')).toBeVisible()
    await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0, { timeout: 60000 })
    await dismissQuickStart(page)
}

async function runQueryAndWaitForResults(page: Page, query: string = 'SELECT 1 AS result'): Promise<void> {
    const sqlInsight = new SqlInsight(page)
    const runButton = page.getByTestId('sql-editor-run-button')

    await sqlInsight.writeQuery(query)
    await sqlInsight.run()

    await expect(runButton).toContainText('Cancel')
    await expect(runButton).toContainText('Run', { timeout: 60000 })
    await expect(page.getByRole('columnheader', { name: /result/i })).toBeVisible()
    await expect(page.getByRole('gridcell', { name: '1' })).toBeVisible()
    await expect(page.getByText('Showing one row')).toBeVisible()
}

test.describe('SQL Editor', () => {
    test.describe.configure({ mode: 'serial' })
    test.setTimeout(120000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            skip_onboarding: true,
            use_current_time: true,
        })
    })

    test.describe('Basic flow', () => {
        test.beforeEach(async ({ page, playwrightSetup }) => {
            await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
            await goToSqlEditor(page)
        })

        test('See SQL Editor', async ({ page }) => {
            await expect(page.getByTestId('editor-scene')).toBeVisible()
            await expect(page.getByText('Sources', { exact: true })).toBeVisible()
            await expect(page.getByTestId('sql-editor-add-source')).toBeVisible()
            await expect(page.getByTestId('sql-editor-output-pane-empty-state')).toBeVisible()
            await expect(page.locator('.scene-name h1 span').getByText('New SQL query', { exact: true })).toBeVisible()
        })

        test('Add source link', async ({ page }) => {
            await page.getByTestId('sql-editor-add-source').click()
            await expect(page).toHaveURL(/.*\/data-warehouse\/new-source/)
        })

        test('Run query', async ({ page }) => {
            await expect(page.getByTestId('sql-editor-output-pane-empty-state')).toBeVisible()
            await runQueryAndWaitForResults(page)
        })

        test('Save view', async ({ page }) => {
            await runQueryAndWaitForResults(page)
            await dismissQuickStart(page)

            await expect(page.getByTestId('sql-editor-save-options-button')).toBeEnabled()
            await page.getByTestId('sql-editor-save-options-button').click()
            await page.getByText('Save as view', { exact: true }).click()

            const nameInput = page.getByTestId('sql-editor-input-save-view-name')
            const uniqueViewName = `test_view_${test.info().repeatEachIndex}_${Date.now()}`
            const submitButton = page.getByRole('button', { name: 'Submit' })
            const saveViewModal = page.getByRole('dialog', { name: 'Save as view' })

            await expect(nameInput).toBeVisible()
            await nameInput.fill(uniqueViewName)
            await expect(submitButton).toBeEnabled()
            await submitButton.click()

            await expect(saveViewModal).not.toBeVisible({ timeout: 60000 })
            await expect(page.locator('.scene-name h1 span').getByText(uniqueViewName, { exact: true })).toBeVisible({
                timeout: 60000,
            })
        })

        test('Materialize view pane', async ({ page }) => {
            await runQueryAndWaitForResults(page)
            await dismissQuickStart(page)

            await expect(page.getByTestId('sql-editor-save-options-button')).toBeEnabled()
            await page.getByTestId('sql-editor-save-options-button').click()
            await page.getByText('Save as view', { exact: true }).click()

            const uniqueViewName = `materialized_test_view_${test.info().repeatEachIndex}_${Date.now()}`
            const nameInput = page.getByTestId('sql-editor-input-save-view-name')
            const saveViewModal = page.getByRole('dialog', { name: 'Save as view' })

            await expect(nameInput).toBeVisible()
            await nameInput.fill(uniqueViewName)
            await page.getByRole('button', { name: 'Submit' }).click()
            await expect(saveViewModal).not.toBeVisible({ timeout: 60000 })
            await expect(page.locator('.scene-name h1 span').getByText(uniqueViewName, { exact: true })).toBeVisible({
                timeout: 60000,
            })

            await dismissQuickStart(page)
            await page.getByTestId('sql-editor-materialization-button').click({ force: true })
            await expect(page.getByTestId('sql-editor-sidebar-query-info-pane')).toBeVisible()
        })

        test('Query variables pane', async ({ page }) => {
            await page.getByTestId('sql-editor-variables-button').click()
            await expect(page.getByPlaceholder('Search variables')).toBeVisible({ timeout: 60000 })
            await expect(page.getByText('No variables found', { exact: true })).toBeVisible({ timeout: 60000 })
            await expect(page.getByText('Manage SQL variables', { exact: true })).toBeVisible({ timeout: 60000 })
        })
    })
})
