/**
 * Examples showing how to use the PostHog workspace setup library
 *
 * This demonstrates different ways to create PostHog workspaces
 * (organizations, projects, teams) for your tests.
 */

import { expect } from '@playwright/test'
import { test, testWithWorkspace, testWithAnalytics } from '../utils/enhanced-test-base'

// Example 1: Manual workspace creation with custom names
test('create custom workspace', async ({ page, workspaceSetup }) => {
    // Create a workspace with custom names
    const workspace = await workspaceSetup.createWorkspace('Acme Corp', 'Web Analytics')

    // Verify workspace was created
    expect(workspace.organizationName).toBe('Acme Corp')
    expect(workspace.projectName).toBe('Web Analytics')
    expect(workspace.userEmail).toBe('test@posthog.com')

    // Login and navigate to the team page
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)

    // Now you're logged in and on the project page - test your feature!
})

// Example 2: Auto-created workspace (most common pattern)
testWithWorkspace('test with pre-created workspace', async ({ page, workspace, workspaceSetup }) => {
    // Workspace already exists with default names

    // Login and navigate automatically
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)

    // Test your feature here
    await expect(page).toHaveTitle(/PostHog/)
})

// Example 3: Analytics workspace with sample data
testWithAnalytics('test insights dashboard', async ({ page, workspace, workspaceSetup }) => {
    // Workspace + analytics data already exists
    expect(workspace.analytics_ready).toBe(true)

    // Navigate to insights page
    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)
    await page.goto(`/project/${workspace.teamId}/insights`)

    // Test insights functionality with sample data
    // (Sample events would be created by the analytics workspace setup)
})

// Example 4: Multiple workspaces in one test
test('compare multiple workspaces', async ({ page, workspaceSetup }) => {
    // Create workspace for Company A
    const companyA = await workspaceSetup.createWorkspace('Company A', 'Mobile App')

    // Create workspace for Company B
    const companyB = await workspaceSetup.createWorkspace('Company B', 'Web App')

    // Test Company A
    await workspaceSetup.loginAndNavigateToTeam(page, companyA.teamId)
    await expect(page.locator('[data-attr="project-name"]')).toContainText('Mobile App')

    // Switch to Company B
    await workspaceSetup.loginAndNavigateToTeam(page, companyB.teamId)
    await expect(page.locator('[data-attr="project-name"]')).toContainText('Web App')
})

// Example 5: Analytics workspace with custom configuration
test('analytics with custom events', async ({ page, workspaceSetup }) => {
    const workspace = await workspaceSetup.createAnalyticsWorkspace({
        organizationName: 'Analytics Corp',
        projectName: 'Dashboard Tests',
        createSampleEvents: true,
        eventCount: 500,
        eventTypes: ['page_view', 'button_click', 'form_submit'],
    })

    await workspaceSetup.loginAndNavigateToTeam(page, workspace.teamId)

    // Test with 500 sample events of specified types
    await page.goto(`/project/${workspace.teamId}/events`)
    // Add your analytics testing logic here
})

// Example 6: Error handling
test('handle setup errors gracefully', async ({ workspaceSetup }) => {
    // Get available setup types
    const availableTypes = await workspaceSetup.getAvailableSetupTypes()

    expect(availableTypes).toContain('organization_with_team')
    expect(availableTypes).toContain('analytics_workspace')
})

// Example 7: Using the convenience function
test('quick workspace creation', async ({ page, request }) => {
    const { createTestWorkspace, createWorkspaceSetup } = await import('../utils/enhanced-test-base')

    // One-off workspace creation
    const result = await createTestWorkspace(request, 'organization_with_team', {
        organization_name: 'Quick Test Org',
    })

    expect(result.success).toBe(true)

    // Or use the main class
    const workspaceSetup = createWorkspaceSetup(request)
    await workspaceSetup.loginAndNavigateToTeam(page, result.result.team_id)
})
