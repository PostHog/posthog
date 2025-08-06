/**
 * Enhanced Playwright test base with database setup capabilities
 */

/* eslint-disable react-hooks/rules-of-hooks */

import {} from '@playwright/test'
import { TestSetup, createTestSetup } from './test-setup'
import { test as baseTest } from './playwright-test-base'

export const LOGIN_USERNAME = process.env.LOGIN_USERNAME || 'test@posthog.com'
export const LOGIN_PASSWORD = process.env.LOGIN_PASSWORD || 'password123'

// Extend the existing test fixtures with testSetup
export const test = baseTest.extend<{ testSetup: TestSetup }>({
    testSetup: async ({ request }, use) => {
        const testSetup = createTestSetup(request)
        await use(testSetup)
    },
})

// Re-export everything from the base test
export { expect } from './playwright-test-base'

/**
 * Test with automatic database cleanup and setup
 * Clears the database before each test to ensure isolation
 */
export const testWithCleanDatabase = test.extend<{}>({
    page: async ({ page, testSetup }, use) => {
        // Clear database before each test
        await testSetup.clearDatabase()

        await use(page)

        // Optionally clear after test too (can be disabled for debugging)
        if (process.env.CLEANUP_AFTER_TEST !== 'false') {
            await testSetup.clearDatabase()
        }
    },
})

/**
 * Test with a pre-configured basic organization
 * Useful for tests that need a minimal setup
 */
export const testWithBasicOrg = test.extend<{
    organizationId: string
    projectId: string
    teamId: string
}>({
    organizationId: async ({ testSetup }, use) => {
        const result = await testSetup.setupBasicOrganization()
        await use(result.result.organization_id)
    },
    projectId: async ({ testSetup }, use) => {
        const result = await testSetup.setupBasicOrganization()
        await use(result.result.project_id)
    },
    teamId: async ({ testSetup }, use) => {
        const result = await testSetup.setupBasicOrganization()
        await use(result.result.team_id)
    },
})

/**
 * Utility function to setup test data at the beginning of a test
 * This is a convenience function for simple setups
 */
export async function withTestSetup<T>(
    testName: string,
    testFn: (setupResult: any) => Promise<T>,
    request: any,
    data?: Record<string, any>
): Promise<T> {
    const testSetup = createTestSetup(request)
    const setupResult = await testSetup.setupTest(testName, { data })
    return testFn(setupResult.result)
}
