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
 * Test with a pre-configured basic organization
 * Useful for tests that need a minimal setup
 * Creates ONE organization and shares the IDs across all fixtures
 */
export const testWithBasicOrg = test.extend<{
    basicOrgSetup: {
        organizationId: string
        projectId: string
        teamId: string
        userId: string
        userEmail: string
    }
}>({
    basicOrgSetup: async ({ testSetup }, use) => {
        const result = await testSetup.setupBasicOrganization()
        await use({
            organizationId: result.result.organization_id,
            projectId: result.result.project_id,
            teamId: result.result.team_id,
            userId: result.result.user_id,
            userEmail: result.result.user_email,
        })
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
