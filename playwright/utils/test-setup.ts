/**
 * Playwright testing library for database setup
 * Allows tests to configure the database before running
 */

import { APIRequestContext, expect } from '@playwright/test'

export interface TestSetupResponse {
    success: boolean
    test_name: string
    result?: any
    error?: string
    available_tests?: string[]
}

export interface TestSetupOptions {
    /** Custom data to pass to the setup function */
    data?: Record<string, any>
    /** Whether to throw an error if setup fails (default: true) */
    throwOnError?: boolean
    /** Base URL for the API (defaults to baseURL from config) */
    baseURL?: string
}

/**
 * Main class for test database setup
 */
export class TestSetup {
    private request: APIRequestContext
    private baseURL: string

    constructor(request: APIRequestContext, baseURL?: string) {
        this.request = request
        this.baseURL = baseURL || process.env.BASE_URL || 'http://localhost:8080'
    }

    /**
     * Setup test data using a named setup function
     *
     * @param testName - Name of the test setup function to run
     * @param options - Additional options for setup
     * @returns Promise<TestSetupResponse>
     */
    async setupTest(testName: string, options: TestSetupOptions = {}): Promise<TestSetupResponse> {
        const { data = {}, throwOnError = true, baseURL } = options
        const url = `${baseURL || this.baseURL}/api/setup_test/${testName}/`

        try {
            const response = await this.request.post(url, {
                data: data,
            })

            const result: TestSetupResponse = await response.json()

            if (!response.ok()) {
                if (throwOnError) {
                    throw new Error(`Test setup failed for '${testName}': ${result.error || 'Unknown error'}`)
                }
            }

            return result
        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error)

            if (throwOnError) {
                throw new Error(`Failed to call test setup endpoint: ${errorMessage}`)
            }

            return {
                success: false,
                test_name: testName,
                error: errorMessage,
            }
        }
    }

    /**
     * Setup a basic organization for testing
     */
    async setupBasicOrganization(organizationName?: string, projectName?: string): Promise<TestSetupResponse> {
        return this.setupTest('basic_organization', {
            data: {
                organization_name: organizationName,
                project_name: projectName,
            },
        })
    }

    /**
     * Setup a user with an organization
     */
    async setupUserWithOrganization(
        options: {
            email?: string
            password?: string
            organizationName?: string
            firstName?: string
            lastName?: string
        } = {}
    ): Promise<TestSetupResponse> {
        return this.setupTest('user_with_organization', {
            data: {
                email: options.email,
                password: options.password,
                organization_name: options.organizationName,
                first_name: options.firstName,
                last_name: options.lastName,
            },
        })
    }

    /**
     * Clear all test data for a clean slate
     */
    async clearDatabase(): Promise<TestSetupResponse> {
        return this.setupTest('empty_database')
    }

    /**
     * Setup environment for feature flags testing
     */
    async setupFeatureFlagsTest(data?: Record<string, any>): Promise<TestSetupResponse> {
        return this.setupTest('feature_flags_test', { data })
    }

    /**
     * Setup environment for insights/analytics testing
     */
    async setupInsightsTest(data?: Record<string, any>): Promise<TestSetupResponse> {
        return this.setupTest('insights_test', { data })
    }

    /**
     * Get list of available test setup functions
     */
    async getAvailableTests(): Promise<string[]> {
        try {
            const response = await this.setupTest('invalid_test_name', { throwOnError: false })
            return response.available_tests || []
        } catch {
            return []
        }
    }
}

/**
 * Helper function to create a TestSetup instance
 */
export function createTestSetup(request: APIRequestContext, baseURL?: string): TestSetup {
    return new TestSetup(request, baseURL)
}

/**
 * Decorator function to setup test data before a test
 *
 * Usage:
 * ```typescript
 * test('my test', async ({ request }) => {
 *   await setupTestData(request, 'basic_organization')
 *   // test code here
 * })
 * ```
 */
export async function setupTestData(
    request: APIRequestContext,
    testName: string,
    data?: Record<string, any>
): Promise<TestSetupResponse> {
    const testSetup = createTestSetup(request)
    return testSetup.setupTest(testName, { data })
}

/**
 * Extend the base test with automatic test setup
 *
 * Usage in test files:
 * ```typescript
 * import { test } from './utils/test-setup'
 *
 * test('my test', async ({ testSetup }) => {
 *   await testSetup.setupBasicOrganization()
 *   // test code here
 * })
 * ```
 */
export { test as baseTest } from './playwright-test-base'

// Re-export for convenience
export { expect } from '@playwright/test'
