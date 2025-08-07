/**
 * Enhanced Playwright test base with PostHog workspace setup capabilities
 *
 * This provides clean test fixtures for creating PostHog workspaces
 * (organizations, projects, teams) before running tests.
 */

/* eslint-disable react-hooks/rules-of-hooks */

import { test as baseTest } from './playwright-test-base'
import { WorkspaceSetup, createWorkspaceSetup, PostHogWorkspace } from './workspace-setup'

/**
 * Base test with workspace setup capabilities
 * Use this for most tests where you want to manually create workspaces
 */
export const test = baseTest.extend<{ workspaceSetup: WorkspaceSetup }>({
    workspaceSetup: async ({ request }, use) => {
        const workspaceSetup = createWorkspaceSetup(request)
        await use(workspaceSetup)
    },
})

/**
 * Test with a pre-created PostHog workspace
 * Use this when you want a workspace automatically created before your test runs
 *
 * The workspace includes: Organization → Project → Team + test@posthog.com user
 */
export const testWithWorkspace = test.extend<{ workspace: PostHogWorkspace }>({
    workspace: async ({ workspaceSetup }, use) => {
        const workspace = await workspaceSetup.createWorkspace()
        await use(workspace)
    },
})

/**
 * Test with a pre-created analytics workspace (includes sample data)
 * Use this for testing insights, dashboards, or anything needing analytics data
 */
export const testWithAnalytics = test.extend<{ workspace: PostHogWorkspace & { analytics_ready: boolean } }>({
    workspace: async ({ workspaceSetup }, use) => {
        const workspace = await workspaceSetup.createAnalyticsWorkspace()
        await use(workspace)
    },
})

// Re-export everything from the base test
export { expect } from './playwright-test-base'

// Re-export workspace setup utilities
export { createWorkspaceSetup, createTestWorkspace } from './workspace-setup'
export type { PostHogWorkspace, WorkspaceSetupOptions } from './workspace-setup'
