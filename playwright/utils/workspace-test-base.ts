/**
 * Workspace-based Playwright test base with PostHog workspace setup capabilities
 *
 * The shared workspace is created once in globalSetup (setup/workspace.setup.ts)
 * and saved to .auth/workspace.json. Tests read from that file via the `workspace` fixture.
 *
 * If a test needs a separate workspace, it can still use `playwrightSetup.createWorkspace()`.
 */
/* eslint-disable react-hooks/rules-of-hooks */
import * as fs from 'fs'

import { WORKSPACE_DATA_PATH } from '../setup/workspace.setup'
import { PlaywrightSetup, PlaywrightWorkspaceSetupResult, createPlaywrightSetup } from './playwright-setup'
import { test as coreTest } from './playwright-test-core'

/**
 * Base test with workspace setup capabilities and a shared workspace fixture
 */
export const test = coreTest.extend<{ playwrightSetup: PlaywrightSetup; workspace: PlaywrightWorkspaceSetupResult }>({
    playwrightSetup: async ({ request, baseURL }, use) => {
        const playwrightSetup = createPlaywrightSetup(request, baseURL)
        await use(playwrightSetup)
    },
    workspace: async ({}, use) => {
        const data = fs.readFileSync(WORKSPACE_DATA_PATH, 'utf-8')
        const workspace = JSON.parse(data) as PlaywrightWorkspaceSetupResult
        await use(workspace)
    },
})

/**
 * Alias for `test` — the shared workspace fixture is always available.
 * Kept for backwards compatibility with existing tests.
 */
export const testWithWorkspace = test

// Re-export everything from the core test
export { expect } from './playwright-test-core'

// Re-export playwright setup utilities
export { createPlaywrightSetup, createTestWorkspace } from './playwright-setup'
export type { PlaywrightWorkspaceSetupResult, PlaywrightSetupOptions } from './playwright-setup'
