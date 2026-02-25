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
 * - User: Configurable via LOGIN_USERNAME/LOGIN_PASSWORD env vars (defaults: test@posthog.com/12345678)
 */
import { APIRequestContext, Page } from '@playwright/test'

import { LOGIN_PASSWORD } from './playwright-test-core'

export interface TestSetupResponse {
    success: boolean
    test_name: string
    result?: any
    error?: string
    available_tests?: string[]
}

export interface PlaywrightSetupVariable {
    name: string
    type: 'String' | 'Number' | 'Boolean' | 'List' | 'Date'
    default_value?: any
}

export interface PlaywrightSetupInsight {
    name: string
    query: Record<string, any>
    variable_indexes?: number[]
}

export interface PlaywrightSetupDashboard {
    name: string
    insight_indexes?: number[]
    filters?: Record<string, any>
    variable_overrides?: Record<string, any>
}

export interface PlaywrightWorkspaceSetupData {
    organization_name?: string
    use_current_time?: boolean
    skip_onboarding?: boolean
    insight_variables?: PlaywrightSetupVariable[]
    insights?: PlaywrightSetupInsight[]
    dashboards?: PlaywrightSetupDashboard[]
}

export interface PlaywrightSetupCreatedVariable {
    id: string
    code_name: string
}

export interface PlaywrightSetupCreatedInsight {
    id: number
    short_id: string
}

export interface PlaywrightSetupCreatedDashboard {
    id: number
}

export interface PlaywrightWorkspaceSetupResult {
    organization_id: string
    team_id: string
    organization_name: string
    team_name: string
    user_id: string
    user_email: string
    personal_api_key: string
    created_variables?: PlaywrightSetupCreatedVariable[]
    created_insights?: PlaywrightSetupCreatedInsight[]
    created_dashboards?: PlaywrightSetupCreatedDashboard[]
}

export interface PlaywrightSetupOptions {
    /** Custom data to pass to the setup function */
    data?: Record<string, any>
    /** Whether to throw an error if setup fails (default: true) */
    throwOnError?: boolean
    /** Base URL for the API (defaults to baseURL from config) */
    baseURL?: string
}

/**
 * Main class for setting up PostHog workspaces in tests
 */
export class PlaywrightSetup {
    private request: APIRequestContext
    private baseURL: string

    constructor(request: APIRequestContext, baseURL?: string) {
        this.request = request
        // Use baseURL from Playwright config if provided, otherwise fall back to environment variable
        this.baseURL = baseURL || process.env.BASE_URL || 'http://localhost:8080'
    }

    /**
     * Call the Django setup endpoint
     */
    async callSetupEndpoint(setupType: string, options: PlaywrightSetupOptions = {}): Promise<TestSetupResponse> {
        const { data = {}, throwOnError = true, baseURL } = options
        const url = `${baseURL || this.baseURL}/api/setup_test/${setupType}/`

        try {
            const response = await this.request.post(url, { data })

            const responseText = await response.text()

            let result: TestSetupResponse
            try {
                result = JSON.parse(responseText)
            } catch (parseError) {
                console.error(`[PlaywrightSetup] Failed to parse response as JSON:`, parseError)
                throw new Error(`Invalid JSON response from setup endpoint: ${responseText}`)
            }

            if (!response.ok() && throwOnError) {
                console.error(`[PlaywrightSetup] Setup failed - Status: ${response.status()}, Result:`, result)
                throw new Error(`Playwright setup failed for '${setupType}': ${result.error || 'Unknown error'}`)
            }

            return result
        } catch (error) {
            const errorMessage = error instanceof Error ? error.message : String(error)
            console.error(`[PlaywrightSetup] Setup endpoint error:`, errorMessage)

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
     * The test user will be a member of the organization.
     */
    async createWorkspace(
        dataOrName?: string | Partial<PlaywrightWorkspaceSetupData>
    ): Promise<PlaywrightWorkspaceSetupResult> {
        const data = typeof dataOrName === 'string' ? { organization_name: dataOrName } : (dataOrName ?? {})
        const result = await this.callSetupEndpoint('organization_with_team', {
            data: data as PlaywrightWorkspaceSetupData,
        })

        if (!result.success) {
            console.error(`[PlaywrightSetup] Workspace creation failed:`, result)
            throw new Error(`Failed to create workspace: ${result.error}`)
        }

        const workspace = result.result as PlaywrightWorkspaceSetupResult

        // Validate required fields (using snake_case field names from schema)
        const requiredFields = ['organization_id', 'team_id', 'personal_api_key'] as const
        const missingFields = requiredFields.filter((field) => !workspace[field])

        if (missingFields.length > 0) {
            console.error(`[PlaywrightSetup] Workspace missing required fields:`, missingFields)
            console.error(`[PlaywrightSetup] Full workspace object:`, workspace)
            throw new Error(`Workspace creation returned incomplete data. Missing fields: ${missingFields.join(', ')}`)
        }

        return workspace
    }

    async login(page: Page, workspace: PlaywrightWorkspaceSetupResult): Promise<void> {
        // Use page.request to share cookies/session with the browser context
        await page.request.post(`${this.baseURL}/api/login/`, {
            data: {
                email: workspace.user_email,
                password: LOGIN_PASSWORD,
            },
        })
    }

    /**
     * Login using workspace credentials and navigate to the team's project page
     *
     * Call this after creating a workspace to automatically login and navigate.
     * The user will end up on /project/{teamId} ready to test.
     */
    async loginAndNavigateToTeam(page: Page, workspace: PlaywrightWorkspaceSetupResult): Promise<void> {
        await this.login(page, workspace)

        await page.goto(`${this.baseURL}/project/${workspace.team_id}`)
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
    return playwrightSetup.callSetupEndpoint(setupType, { data })
}
