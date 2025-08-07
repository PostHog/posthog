/**
 * PostHog Playwright Setup for Playwright Tests
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
} from '~/queries/schema/schema-general'

export interface PlaywrightSetupOptions {
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
    personalApiKey: string
}

/**
 * Main class for setting up PostHog workspaces in tests
 */
export class PlaywrightSetup {
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
        options: PlaywrightSetupOptions = {}
    ): Promise<TestSetupResponse> {
        const { data = {}, throwOnError = true, baseURL } = options
        const url = `${baseURL || this.baseURL}/api/setup_test/${setupType}/`

        try {
            const response = await this.request.post(url, { data })
            const result: TestSetupResponse = await response.json()

            if (!response.ok() && throwOnError) {
                throw new Error(`Playwright setup failed for '${setupType}': ${result.error || 'Unknown error'}`)
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
     * Login as test@posthog.com and navigate to the team's project page
     *
     * Call this after creating a workspace to automatically login and navigate.
     * The user will end up on /project/{teamId} ready to test.
     */
    async loginAndNavigateToTeam(page: Page, teamId: string): Promise<void> {
        await this.request.post(`${this.baseURL}/api/login/`, {
            data: {
                email: 'test@posthog.com',
                password: '12345678',
            },
        })

        await page.goto(`${this.baseURL}/project/${teamId}`)
    }
}

/**
 * Helper function to create a PlaywrightSetup instance
 */
export function createPlaywrightSetup(request: APIRequestContext, baseURL?: string): PlaywrightSetup {
    return new PlaywrightSetup(request, baseURL)
}

/**
 * One-off workspace creation (for simple cases)
 */
export async function createTestWorkspace(
    request: APIRequestContext,
    setupType: string,
    data?: Record<string, any>
): Promise<TestSetupResponse> {
    const playwrightSetup = createPlaywrightSetup(request)
    return playwrightSetup['callSetupEndpoint'](setupType, { data })
}

// Backward compatibility aliases
export const WorkspaceSetup = PlaywrightSetup
export const createWorkspaceSetup = createPlaywrightSetup
export type WorkspaceSetupOptions = PlaywrightSetupOptions

// Re-export types for convenience
export type { TestSetupResponse, BasicOrganizationSetupData, BasicOrganizationSetupResult }
