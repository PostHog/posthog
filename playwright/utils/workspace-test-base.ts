/**
 * Workspace-based Playwright test base with PostHog workspace setup capabilities
 *
 * This provides clean test fixtures for creating PostHog workspaces
 * (organizations, projects, teams) before running tests.
 *
 * Unlike the legacy playwright-test-base, this does NOT auto-login,
 * giving you full control over authentication with workspace-specific users.
 */
/* eslint-disable react-hooks/rules-of-hooks */
import { PlaywrightSetup, PlaywrightWorkspaceSetupResult, createPlaywrightSetup } from './playwright-setup'
import { test as coreTest } from './playwright-test-core'

/**
 * Base test with workspace setup capabilities
 * Use this for most tests where you want to manually create workspaces
 */
export const test = coreTest.extend<{ playwrightSetup: PlaywrightSetup; workspaceSetup: PlaywrightSetup }>({
    playwrightSetup: async ({ request, baseURL }, use) => {
        const playwrightSetup = createPlaywrightSetup(request, baseURL)
        await use(playwrightSetup)
    },
})

/**
 * Test with a pre-created PostHog workspace
 * Use this when you want a workspace automatically created before your test runs
 *
 * The workspace includes: Organization → Project → Team + test@posthog.com user
 */
export const testWithWorkspace = test.extend<{ workspace: PlaywrightWorkspaceSetupResult }>({
    workspace: async ({ playwrightSetup }, use) => {
        const workspace = await playwrightSetup.createWorkspace()
        await use(workspace)
    },
})

// Re-export everything from the core test
export { expect } from './playwright-test-core'

// Re-export playwright setup utilities
export { createPlaywrightSetup, createTestWorkspace } from './playwright-setup'
export type { PlaywrightWorkspaceSetupResult, PlaywrightSetupOptions } from './playwright-setup'
