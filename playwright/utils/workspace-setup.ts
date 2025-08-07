/**
 * PostHog Workspace Setup for Playwright Tests
 *
 * This library helps you create PostHog workspaces (organizations, projects, teams)
 * and test data before running Playwright tests.
 *
 * Key concepts:
 * - Organization: Top-level account (e.g., "Acme Corp")
 * - Project: Container within an org (e.g., "Web App", "Mobile App")
 * - Team: Environment within project where data lives (e.g., "Production", "Staging")
 * - User: test@posthog.com with password 12345678 (auto-created and added to org)
 */

import { APIRequestContext, Page } from '@playwright/test'
import type {
    TestSetupResponse,
    BasicOrganizationSetupData,
    BasicOrganizationSetupResult,
    InsightsTestSetupData,
    InsightsTestSetupResult,
} from '~/queries/schema/schema-general'

export interface WorkspaceSetupOptions {
    /** Custom data to pass to the setup function */
    data?: Record<string, any>
    /** Whether to throw an error if setup fails (default: true) */
    throwOnError?: boolean
    /** Base URL for the API (defaults to baseURL from config) */
    baseURL?: string
}

export interface PostHogWorkspace {
    organizationId: string
    projectId: string
    teamId: string
    organizationName: string
    projectName: string
    teamName: string
    userId: string
    userEmail: string
}

/**
 * Main class for setting up PostHog workspaces in tests
 */
export class WorkspaceSetup {
    private request: APIRequestContext
    private baseURL: string

    constructor(request: APIRequestContext, baseURL?: string) {
        this.request = request
        this.baseURL = baseURL || process.env.BASE_URL || 'http://localhost:8080'
    }

    /**
     * Internal method to call the Django setup endpoint
     */
    private async callSetupEndpoint(
        setupType: string,
        options: WorkspaceSetupOptions = {}
    ): Promise<TestSetupResponse> {
        const { data = {}, throwOnError = true, baseURL } = options
        const url = `${baseURL || this.baseURL}/api/setup_test/${setupType}/`

        try {
            const response = await this.request.post(url, { data })
            const result: TestSetupResponse = await response.json()

            if (!response.ok() && throwOnError) {
                throw new Error(`Workspace setup failed for '${setupType}': ${result.error || 'Unknown error'}`)
            }

            return result
        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error)

            if (throwOnError) {
                throw new Error(`Failed to call setup endpoint: ${errorMessage}`)
            }

            return {
                success: false,
                test_name: setupType,
                error: errorMessage,
            }
        }
    }

    /**
     * Creates a complete PostHog workspace: Organization → Project → Team + test@posthog.com user
     *
     * This is the main setup method - creates everything you need for most tests.
     * The test@posthog.com user will be a member of the organization.
     */
    async createWorkspace(organizationName?: string, projectName?: string): Promise<PostHogWorkspace> {
        const result = await this.callSetupEndpoint('organization_with_team', {
            data: {
                organization_name: organizationName,
                project_name: projectName,
            } as BasicOrganizationSetupData,
        })

        if (!result.success) {
            throw new Error(`Failed to create workspace: ${result.error}`)
        }

        return result.result as PostHogWorkspace
    }

    /**
     * Creates a workspace with sample analytics data for testing insights/dashboards
     */
    async createAnalyticsWorkspace(options?: {
        organizationName?: string
        projectName?: string
        createSampleEvents?: boolean
        eventCount?: number
        eventTypes?: string[]
    }): Promise<PostHogWorkspace & { analytics_ready: boolean }> {
        const result = await this.callSetupEndpoint('analytics_workspace', {
            data: {
                organization_name: options?.organizationName,
                project_name: options?.projectName,
                create_sample_events: options?.createSampleEvents,
                event_count: options?.eventCount,
                event_types: options?.eventTypes,
            } as InsightsTestSetupData,
        })

        if (!result.success) {
            throw new Error(`Failed to create analytics workspace: ${result.error}`)
        }

        return result.result
    }

    /**
     * Login as test@posthog.com and navigate to the team's project page
     *
     * Call this after creating a workspace to automatically login and navigate.
     * The user will end up on /project/{teamId} ready to test.
     */
    async loginAndNavigateToTeam(page: Page, teamId: string): Promise<void> {
        // Login via API (faster than UI login)
        await this.request.post(`${this.baseURL}/api/login/`, {
            data: {
                email: 'test@posthog.com',
                password: '12345678',
            },
        })

        // Navigate to the team's project page
        await page.goto(`${this.baseURL}/project/${teamId}`)
    }

    /**
     * Get list of available workspace setup types
     */
    async getAvailableSetupTypes(): Promise<string[]> {
        try {
            const response = await this.callSetupEndpoint('invalid_setup_type', { throwOnError: false })
            return response.available_tests || []
        } catch {
            return []
        }
    }
}

/**
 * Helper function to create a WorkspaceSetup instance
 */
export function createWorkspaceSetup(request: APIRequestContext, baseURL?: string): WorkspaceSetup {
    return new WorkspaceSetup(request, baseURL)
}

/**
 * One-off workspace creation (for simple cases)
 */
export async function createTestWorkspace(
    request: APIRequestContext,
    setupType: string,
    data?: Record<string, any>
): Promise<TestSetupResponse> {
    const workspaceSetup = createWorkspaceSetup(request)
    return workspaceSetup['callSetupEndpoint'](setupType, { data })
}

// Re-export types for convenience
export type {
    TestSetupResponse,
    BasicOrganizationSetupData,
    BasicOrganizationSetupResult,
    InsightsTestSetupData,
    InsightsTestSetupResult,
    WorkspaceSetupOptions,
}
