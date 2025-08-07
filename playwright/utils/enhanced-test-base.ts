/**
 * Enhanced Playwright test base with PostHog workspace setup capabilities
 *
 * This provides clean test fixtures for creating PostHog workspaces
 * (organizations, projects, teams) before running tests.
 */

/* eslint-disable react-hooks/rules-of-hooks */

import { test as baseTest } from './playwright-test-base'
import { PlaywrightSetup, createPlaywrightSetup, PostHogWorkspace } from './playwright-setup'

/**
 * Base test with workspace setup capabilities
 * Use this for most tests where you want to manually create workspaces
 */
export const test = baseTest.extend<{ playwrightSetup: PlaywrightSetup; workspaceSetup: PlaywrightSetup }>({
    playwrightSetup: async ({ request }, use) => {
        const playwrightSetup = createPlaywrightSetup(request)
        await use(playwrightSetup)
    },
    // Backward compatibility alias
    workspaceSetup: async ({ playwrightSetup }, use) => {
        await use(playwrightSetup)
    },
})

/**
 * Test with a pre-created PostHog workspace
 * Use this when you want a workspace automatically created before your test runs
 *
 * The workspace includes: Organization → Project → Team + test@posthog.com user
 */
export const testWithWorkspace = test.extend<{ workspace: PostHogWorkspace }>({
    workspace: async ({ playwrightSetup }, use) => {
        const workspace = await playwrightSetup.createWorkspace()
        await use(workspace)
    },
})

// Re-export everything from the base test
export { expect } from './playwright-test-base'

// Re-export playwright setup utilities
export { createPlaywrightSetup, createTestWorkspace } from './playwright-setup'
export type { PostHogWorkspace, PlaywrightSetupOptions } from './playwright-setup'

// Backward compatibility exports
export { createPlaywrightSetup as createWorkspaceSetup } from './playwright-setup'
export type { PlaywrightSetupOptions as WorkspaceSetupOptions } from './playwright-setup'
