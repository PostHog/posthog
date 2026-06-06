/**
 * Examples showing how to use the PostHog playwright setup library
 *
 * This demonstrates different ways to create PostHog workspaces
 * (organizations, projects, teams) for your tests.
 */
import { expect } from '@playwright/test'

import { test, testWithWorkspace } from '../utils/workspace-test-base'

test('create custom workspace', async ({ page, playwrightSetup }) => {
    // Create a workspace with custom names
    const workspace = await playwrightSetup.createWorkspace('Acme Corp')

    // Verify workspace was created
    expect(workspace.organization_name).toBe('Acme Corp')
    expect(workspace.personal_api_key).toBeTruthy()

    // Login and navigate to the team page
    await playwrightSetup.loginAndNavigateToTeam(page, workspace)

    // Now you're logged in and on the project page - test your feature!
})

testWithWorkspace('test with pre-created workspace', async ({ page, workspace, playwrightSetup }) => {
    // Workspace already exists with default names

    // Login and navigate automatically
    await playwrightSetup.loginAndNavigateToTeam(page, workspace)

    // Test your feature here
    await expect(page).toHaveTitle(/PostHog/)
})

test('test with API calls', async ({ page, playwrightSetup }) => {
    const workspace = await playwrightSetup.createWorkspace('API Integration Tests')

    await expect(workspace.personal_api_key).toMatch(/^phx_/)
    const apiKey = workspace.personal_api_key

    const response = await page.request.get(`/api/projects/${workspace.team_id}/`, {
        headers: {
            Authorization: `Bearer ${apiKey}`,
        },
    })

    expect(response.ok()).toBe(true)

    await playwrightSetup.loginAndNavigateToTeam(page, workspace)
})
