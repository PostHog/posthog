/**
 * Screenshot tests for workflows product
 */
import { expect } from '@playwright/test'

import { PlaywrightWorkspaceSetupResult, test } from '../utils/workspace-test-base'

test.describe('Workflows', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        // Create a workspace with custom names (once for all tests)
        workspace = await playwrightSetup.createWorkspace('Workflow Users Inc.')

        // Verify workspace was created
        expect(workspace.organization_name).toBe('Workflow Users Inc.')
        expect(workspace.personal_api_key).toBeTruthy()
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        if (!workspace) {
            throw new Error('Workspace was not initialized before tests')
        }
        // Login and navigate to the team page
        await playwrightSetup.loginAndNavigateToTeam(page, workspace)

        // Navigate to workflows page
        await page.goto('/workflows')
    })

    // ──────────────────────────────────────────
    // Top-level scene tabs
    // ──────────────────────────────────────────

    test.describe('workflows tab', () => {
        test.beforeEach(async ({ page }) => {
            await page.waitForSelector('[data-attr="new-workflow"]', { timeout: 10000 })
            await page.waitForSelector('[data-attr="workflows-table"][data-loading="false"]', { timeout: 10000 })
        })

        test('shows workflows list page with table and controls', async ({ page }) => {
            await expect(page.getByText('Loading', { exact: true })).not.toBeVisible({ timeout: 5000 })

            await expect(page).toHaveScreenshot('workflows-list.png', { fullPage: true })
        })

        test('new workflow button opens modal with template chooser', async ({ page }) => {
            await page.click('[data-attr="new-workflow"]')
            await page.waitForSelector('[data-attr="new-workflow-chooser"]', { timeout: 3000 })

            await expect(page.locator('[data-attr="new-workflow-chooser"]')).toBeVisible()
            await expect(page.locator('[data-attr="create-workflow-blank"]')).toBeVisible()

            await expect(page).toHaveScreenshot('new-workflow-modal.png', { fullPage: true })
        })

        test('create blank workflow and see editor', async ({ page }) => {
            await page.click('[data-attr="new-workflow"]')
            await page.waitForSelector('[data-attr="new-workflow-chooser"]', { timeout: 3000 })
            await page.click('[data-attr="create-workflow-blank"]', { force: true })

            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 10000 })
            await expect(page.getByText('Loading', { exact: true })).not.toBeVisible({ timeout: 5000 })

            await expect(page).toHaveScreenshot('new-workflow.png', { fullPage: true })
        })
    })

    test.describe('library tab', () => {
        test('shows message templates table', async ({ page }) => {
            await page.goto('/workflows/library')
            await page.waitForSelector('[data-attr="message-templates-table"]', { timeout: 10000 })
            await expect(page.getByText('Loading', { exact: true })).not.toBeVisible({ timeout: 5000 })

            // The new template button should be visible
            await expect(page.locator('[data-attr="new-message-button"]')).toBeVisible()

            await expect(page).toHaveScreenshot('library-tab.png', { fullPage: true })
        })
    })

    test.describe('channels tab', () => {
        test.skip('shows message channels section', async ({ page }) => {
            await page.goto('/workflows/channels')
            await page.waitForSelector('[data-attr="message-channels"]', { timeout: 10000 })
            await expect(page.getByText('Loading', { exact: true })).not.toBeVisible({ timeout: 5000 })

            // Wait for loading skeletons to disappear
            await expect(page.locator('[data-attr="message-channels"] .LemonSkeleton').first()).not.toBeVisible()

            await expect(page).toHaveScreenshot('channels-tab.png', { fullPage: true })
        })
    })

    test.describe('opt-outs tab', () => {
        test('shows opt-out scene with categories and opt-out list', async ({ page }) => {
            await page.goto('/workflows/opt-outs')
            await page.waitForSelector('[data-attr="opt-out-scene"]', { timeout: 10000 })
            await expect(page.getByText('Loading', { exact: true })).not.toBeVisible({ timeout: 5000 })

            // The new category button should be visible
            await expect(page.locator('[data-attr="new-optout-category"]')).toBeVisible()
            // Section headings should be present
            await expect(page.getByRole('heading', { name: 'Message categories' })).toBeVisible()
            await expect(page.getByText('Marketing opt-out list')).toBeVisible()

            // Wait for skeleton loaders to finish
            await expect(page.locator('[data-attr="opt-out-scene"] .LemonSkeleton')).not.toBeAttached({
                timeout: 10000,
            })

            await expect(page).toHaveScreenshot('opt-outs-tab.png', { fullPage: true })
        })
    })

    test.describe('tab navigation', () => {
        test.skip('can navigate between all top-level tabs', async ({ page }) => {
            await page.waitForSelector('[data-attr="workflows-scene"]', { timeout: 10000 })
            await page.waitForSelector('[data-attr="workflows-table"][data-loading="false"]', { timeout: 10000 })

            // Navigate to Library tab
            await page.click('[data-attr="workflows-scene-tabs"] >> text=Library')
            await page.waitForSelector('[data-attr="message-templates-table"]', { timeout: 10000 })
            await expect(page).toHaveURL(/\/workflows\/library/)

            // Navigate to Channels tab
            await page.click('[data-attr="workflows-scene-tabs"] >> text=Channels')
            await page.waitForSelector('[data-attr="message-channels"]', { timeout: 10000 })
            await expect(page).toHaveURL(/\/workflows\/channels/)

            // Navigate to Opt-outs tab
            await page.click('[data-attr="workflows-scene-tabs"] >> text=Opt-outs')
            await page.waitForSelector('[data-attr="opt-out-scene"]', { timeout: 10000 })
            await expect(page).toHaveURL(/\/workflows\/opt-outs/)

            // Navigate back to Workflows tab
            await page.click('[data-attr="workflows-scene-tabs"] >> text=Workflows')
            await page.waitForSelector('[data-attr="workflows-table"][data-loading="false"]', { timeout: 10000 })
            await expect(page).toHaveURL(/\/workflows\/workflows|\/workflows$/)
        })
    })

    // ──────────────────────────────────────────
    // Single workflow view tabs
    // ──────────────────────────────────────────

    test.describe('single workflow view', () => {
        test.beforeEach(async ({ page }) => {
            // Create a blank workflow to test with
            await page.waitForSelector('[data-attr="new-workflow"]', { timeout: 10000 })
            await page.waitForSelector('[data-attr="workflows-table"][data-loading="false"]', { timeout: 10000 })

            await page.click('[data-attr="new-workflow"]')
            await page.waitForSelector('[data-attr="new-workflow-chooser"]', { timeout: 3000 })
            await page.click('[data-attr="create-workflow-blank"]', { force: true })

            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 10000 })
            await expect(page.getByText('Loading', { exact: true })).not.toBeVisible({ timeout: 5000 })

            // Configure the event trigger - click the trigger node to select it, then add an event
            await page.locator('[data-attr="workflow-editor"]').getByText('Trigger').click()
            await page.waitForSelector('[data-attr="workflow-trigger"]', { timeout: 5000 })
            await page.getByTestId('add-action-event-button').click()

            // Save the workflow so we get a real ID and tabs appear
            await page.click('[data-attr="workflow-save"]')
            // Wait for save to complete and URL to update to a real workflow ID
            await page.waitForURL(/\/workflows\/[a-zA-Z0-9-]+\/workflow/, { timeout: 10000 })
        })

        test('workflow tab shows the editor canvas', async ({ page }) => {
            await expect(page.locator('[data-attr="workflow-editor"]')).toBeVisible()
            await expect(page.locator('[data-attr="workflow-launch"]')).toBeVisible()

            await expect(page).toHaveScreenshot('workflow-view-editor.png', { fullPage: true })
        })

        test('invocations tab shows logs viewer', async ({ page }) => {
            // Click on Invocations tab
            await page.getByRole('tab', { name: /Invocations/ }).click()
            await page.waitForSelector('[data-attr="workflow-logs"]', { timeout: 10000 })

            await expect(page).toHaveScreenshot('workflow-view-logs.png', { fullPage: true })
        })

        test('metrics tab shows metrics dashboard', async ({ page }) => {
            // Click on Metrics tab
            await page.getByRole('tab', { name: 'Metrics' }).click()
            await page.waitForSelector('[data-attr="workflow-metrics"]', { timeout: 10000 })

            await expect(page).toHaveScreenshot('workflow-view-metrics.png', { fullPage: true })
        })

        test('history tab shows activity log', async ({ page }) => {
            // Click on History tab
            await page.getByRole('tab', { name: 'History' }).click()
            await page.waitForSelector('[data-attr="activity-log"]', { timeout: 10000 })

            await expect(page).toHaveScreenshot('workflow-view-history.png', { fullPage: true })
        })

        test('can navigate between all workflow tabs', async ({ page }) => {
            // Start on workflow tab
            await expect(page.locator('[data-attr="workflow-editor"]')).toBeVisible()

            // Go to Invocations
            await page.getByRole('tab', { name: /Invocations/ }).click()
            await page.waitForSelector('[data-attr="workflow-logs"]', { timeout: 10000 })
            await expect(page).toHaveURL(/\/logs/)

            // Go to Metrics
            await page.getByRole('tab', { name: 'Metrics' }).click()
            await page.waitForSelector('[data-attr="workflow-metrics"]', { timeout: 10000 })
            await expect(page).toHaveURL(/\/metrics/)

            // Go to History
            await page.getByRole('tab', { name: 'History' }).click()
            await expect(page).toHaveURL(/\/history/)

            // Go back to Workflow
            await page.getByRole('tab', { name: 'Workflow' }).click()
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 10000 })
            await expect(page).toHaveURL(/\/workflow/)
        })
    })
})
