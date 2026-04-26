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

export interface PlaywrightSetupEvent {
    event: string
    distinct_id: string
    timestamp: string // ISO 8601 timestamp
    properties?: Record<string, any>
}

export interface PlaywrightSetupPerson {
    distinct_ids: string[]
    properties?: Record<string, any>
}

export interface PlaywrightSetupExperiment {
    name: string
    feature_flag_key: string
    start_date?: string // ISO 8601 — if set, experiment is created as RUNNING
    metrics?: Record<string, any>[]
    metrics_secondary?: Record<string, any>[]
}

export interface PlaywrightWorkspaceSetupData {
    organization_name?: string
    use_current_time?: boolean
    skip_onboarding?: boolean
    no_demo_data?: boolean
    insight_variables?: PlaywrightSetupVariable[]
    insights?: PlaywrightSetupInsight[]
    dashboards?: PlaywrightSetupDashboard[]
    events?: PlaywrightSetupEvent[]
    persons?: PlaywrightSetupPerson[]
    experiments?: PlaywrightSetupExperiment[]
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

export interface PlaywrightSetupCreatedExperiment {
    id: number
    feature_flag_key: string
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
    created_experiments?: PlaywrightSetupCreatedExperiment[]
}

export interface PlaywrightSetupOptions {
    /** Custom data to pass to the setup function */
    data?: Record<string, any>
    /** Whether to throw an error if setup fails (default: true) */
    throwOnError?: boolean
    /** Base URL for the API (defaults to baseURL from config) */
    baseURL?: string
    /** Number of retry attempts on transient failures (default: 3) */
    maxRetries?: number
}

class NonRetryableError extends Error {
    constructor(message: string) {
        super(message)
        this.name = 'NonRetryableError'
    }
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
     * Call the Django setup endpoint with automatic retry on transient failures.
     * Retries up to `maxRetries` times (default 3) with exponential backoff
     * (2s, 4s between attempts) to handle intermittent API timeouts in CI.
     */
    async callSetupEndpoint(setupType: string, options: PlaywrightSetupOptions = {}): Promise<TestSetupResponse> {
        const { data = {}, throwOnError = true, baseURL, maxRetries = 3 } = options
        const url = `${baseURL || this.baseURL}/api/setup_test/${setupType}/`

        let lastError: Error | undefined

        for (let attempt = 1; attempt <= maxRetries; attempt++) {
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

                if (!response.ok()) {
                    // Server errors (5xx) are retryable; client errors (4xx) are not
                    if (response.status() >= 500 && attempt < maxRetries) {
                        console.warn(
                            `[PlaywrightSetup] Server error ${response.status()} on attempt ${attempt}/${maxRetries} for '${setupType}', retrying...`
                        )
                        await this.delay(2000 * Math.pow(2, attempt - 1))
                        continue
                    }
                    if (throwOnError) {
                        console.error(`[PlaywrightSetup] Setup failed - Status: ${response.status()}, Result:`, result)
                        throw new NonRetryableError(
                            `Playwright setup failed for '${setupType}': ${result.error || 'Unknown error'}`
                        )
                    }
                }

                return result
            } catch (error) {
                // Non-retryable errors (e.g. 4xx) should not be retried
                if (error instanceof NonRetryableError) {
                    throw error
                }

                lastError = error instanceof Error ? error : new Error(String(error))

                if (attempt < maxRetries) {
                    const delayMs = 2000 * Math.pow(2, attempt - 1)
                    console.warn(
                        `[PlaywrightSetup] Attempt ${attempt}/${maxRetries} failed for '${setupType}': ${lastError.message}. Retrying in ${delayMs}ms...`
                    )
                    await this.delay(delayMs)
                    continue
                }

                console.error(
                    `[PlaywrightSetup] All ${maxRetries} attempts failed for '${setupType}':`,
                    lastError.message
                )

                if (throwOnError) {
                    throw new Error(`Failed to call setup endpoint after ${maxRetries} attempts: ${lastError.message}`)
                }

                return {
                    success: false,
                    test_name: setupType,
                    error: lastError.message,
                }
            }
        }

        // Should not be reached, but satisfies TypeScript
        throw lastError || new Error(`Failed to call setup endpoint after ${maxRetries} attempts`)
    }

    private delay(ms: number): Promise<void> {
        return new Promise((resolve) => setTimeout(resolve, ms))
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
        await page.goto(`${this.baseURL}/login`)
        await page.evaluate(
            async ({ email, password }) => {
                await fetch('/api/login/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ email, password }),
                })
            },
            {
                email: workspace.user_email,
                password: LOGIN_PASSWORD,
            }
        )
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
