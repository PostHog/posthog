/**
 * Screenshot tests for workflows product
 */
import { expect } from '@playwright/test'

import { test } from '../utils/workspace-test-base'

test.describe('Workflows', () => {
    test.beforeEach(async ({ page, playwrightSetup, workspace }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace)
        await page.goto('/workflows')
    })

    test('workflows list page', async ({ page }) => {
        // Wait for the page to load
        await page.waitForSelector('[data-attr="new-workflow"]', { timeout: 10000 })

        // Wait for workflows table to finish loading
        await page.waitForSelector('[data-attr="workflows-table"][data-loading="false"]', { timeout: 10000 })

        // Wait for any sidebar loading to finish
        await expect(page.getByText('Loading', { exact: true })).not.toBeVisible({ timeout: 5000 })

        // Take a screenshot of the workflows list page
        await expect(page).toHaveScreenshot('workflows-list.png', {
            fullPage: true,
        })
    })

    test('setup new workflow', async ({ page }) => {
        // Wait for the page to load
        await page.waitForSelector('[data-attr="new-workflow"]', { timeout: 10000 })

        // Wait for workflows table to finish loading before clicking
        await page.waitForSelector('[data-attr="workflows-table"][data-loading="false"]', { timeout: 10000 })

        // Click on the "New Workflow" button
        await page.click('[data-attr="new-workflow"]')

        // Wait for the new workflow modal to appear
        await page.waitForSelector('[data-attr="new-workflow-chooser"]', { timeout: 3000 })

        // Select the "Empty workflow" template
        await page.click('[data-attr="create-workflow-blank"]', { force: true })

        // Wait for the new workflow page to load
        await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 10000 })

        // Wait for any loading to finish
        await expect(page.getByText('Loading', { exact: true })).not.toBeVisible({ timeout: 5000 })

        // Take a screenshot of the new workflow page
        await expect(page).toHaveScreenshot('new-workflow.png', {
            fullPage: true,
        })
    })
})
