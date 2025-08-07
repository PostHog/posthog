/**
 * Examples showing how to use the PostHog playwright setup library
 *
 * This demonstrates different ways to create PostHog workspaces
 * (organizations, projects, teams) for your tests.
 */

import { expect } from '@playwright/test'
import { test, testWithWorkspace } from '../utils/enhanced-test-base'

// Example 1: Manual workspace creation with custom names
test('create custom workspace', async ({ page, playwrightSetup }) => {
    // Create a workspace with custom names
    const workspace = await playwrightSetup.createWorkspace('Acme Corp', 'Web Analytics')

    // Verify workspace was created
    expect(workspace.organization_name).toBe('Acme Corp')
    expect(workspace.user_email).toBe('test@posthog.com')
    expect(workspace.personal_api_key).toBeTruthy()

    // Login and navigate to the team page
    await playwrightSetup.loginAndNavigateToTeam(page, workspace.team_id)

    // Now you're logged in and on the project page - test your feature!
})

// Example 2: Auto-created workspace (most common pattern)
testWithWorkspace('test with pre-created workspace', async ({ page, workspace, playwrightSetup }) => {
    // Workspace already exists with default names

    // Login and navigate automatically
    await playwrightSetup.loginAndNavigateToTeam(page, workspace.team_id)

    // Test your feature here
    await expect(page).toHaveTitle(/PostHog/)
})

// Example 3: Test with API key access
test('test API key functionality', async ({ page, playwrightSetup }) => {
    const workspace = await playwrightSetup.createWorkspace('API Test Org')

    // You now have a personal API key for API testing

    expect(workspace.personal_api_key).toMatch(/^phx_/)

    await playwrightSetup.loginAndNavigateToTeam(page, workspace.team_id)

    // Test features that might need API access
})

// Example 4: Multiple workspaces in one test
test('compare multiple workspaces', async ({ page, playwrightSetup }) => {
    // Create workspace for Company A
    const companyA = await playwrightSetup.createWorkspace('Company A', 'Mobile App')

    // Create workspace for Company B
    const companyB = await playwrightSetup.createWorkspace('Company B', 'Web App')

    // Test Company A
    await playwrightSetup.loginAndNavigateToTeam(page, companyA.team_id)
    await expect(page.locator('[data-attr="project-name"]')).toContainText('Mobile App')

    // Switch to Company B
    await playwrightSetup.loginAndNavigateToTeam(page, companyB.team_id)
    await expect(page.locator('[data-attr="project-name"]')).toContainText('Web App')
})

// Example 5: Using API key for API testing
test('test with API calls', async ({ page, playwrightSetup }) => {
    const workspace = await playwrightSetup.createWorkspace('API Integration Tests')

    // Use the API key for making API calls in your test
    const apiKey = workspace.personal_api_key

    // Example: Test an API endpoint
    const response = await page.request.get(`/api/projects/${workspace.team_id}/`, {
        headers: {
            Authorization: `Bearer ${apiKey}`,
        },
    })

    expect(response.ok()).toBe(true)

    await playwrightSetup.loginAndNavigateToTeam(page, workspace.team_id)
    // Continue with UI testing
})

// Example 6: Error handling
test('handle setup errors gracefully', async ({ playwrightSetup }) => {
    // Test that invalid setup types return proper errors
    try {
        await playwrightSetup.createWorkspace()
    } catch (error) {
        // Should not throw for valid setup
        throw error
    }

    // This test demonstrates that the basic setup works
    expect(true).toBe(true)
})

// Example 7: Using the convenience function
test('quick workspace creation', async ({ page, request }) => {
    const { createTestWorkspace, createPlaywrightSetup } = await import('../utils/enhanced-test-base')

    // One-off workspace creation
    const result = await createTestWorkspace(request, 'organization_with_team', {
        organization_name: 'Quick Test Org',
    })

    expect(result.success).toBe(true)

    // Or use the main class
    const playwrightSetup = createPlaywrightSetup(request)
    await playwrightSetup.loginAndNavigateToTeam(page, result.result.team_id)
})
