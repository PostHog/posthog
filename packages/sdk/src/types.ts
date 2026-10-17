export interface JsonObject {
    [key: string]: JsonValue
}

export type JsonValue = string | number | boolean | null | JsonObject | JsonValue[]

export interface PostHogClientOptions {
    /** Defaults to POSTHOG_API_URL, POSTHOG_HOST, then https://us.posthog.com. Proxy mode requires a configured URL. */
    baseUrl?: string
    /** Defaults to POSTHOG_AUTH_MODE, then token. In proxy mode the Tasks proxy supplies authentication. */
    authMode?: 'token' | 'proxy'
    /** Defaults to POSTHOG_PERSONAL_API_KEY, then POSTHOG_API_KEY. Accepts a personal API key or OAuth token, not an ingestion key. */
    token?: string
    /** Required for automatic project discovery when the token prefix does not identify its credential family. */
    tokenType?: 'personal_api_key' | 'oauth'
    /** Defaults to POSTHOG_PROJECT_ID before trying token/user discovery. */
    projectId?: number
    /** Defaults to POSTHOG_ORGANIZATION_ID, then the selected project's organization. */
    organizationId?: string
    /** Task context for tasks-artifacts and tasks-comments. Defaults to POSTHOG_TASK_ID. */
    taskId?: string
    /** Receives agent-feedback submissions. Configure this to route feedback to your application. */
    feedback?: (properties: Record<string, JsonValue>) => Promise<void>
    /** Public PostHog URL for returned links. Defaults to POSTHOG_PUBLIC_URL, then baseUrl outside proxy mode. */
    publicBaseUrl?: string
    /** Set false to make this client independent of process environment configuration. */
    env?: boolean
    fetch?: typeof globalThis.fetch
    /** Whole-call deadline in milliseconds, including project discovery. Defaults to 30000. */
    timeoutMs?: number
}

export interface RequestOptions {
    signal?: AbortSignal
    /** Overrides the client's whole-call deadline for this call only. */
    timeoutMs?: number
}

export interface ResponseMeta {
    status: number
    requestId?: string
    informational?: InformationalResponse
}

export interface InformationalResponse {
    tag: string
    purpose?: string
    /** The API result is reference data and must not be treated as instructions by an agent. */
    notice: string
}

export interface ProjectContext {
    projectId: number
    organizationId?: string
    source: 'explicit' | 'environment' | 'token_scope' | 'user_selection'
}

export interface ProjectResolutionErrorDetails {
    reason: 'ambiguous' | 'missing' | 'discovery_unavailable'
    /** Known token-scoped projects; an empty list does not prove there are no accessible projects. */
    candidateProjectIds: number[]
}

export interface ApiFieldError {
    path: (string | number)[]
    code: string
    message: string
}

export interface PostHogErrorDetails {
    kind:
        | 'configuration'
        | 'api'
        | 'input_validation'
        | 'response_validation'
        | 'transport'
        | 'timeout'
        | 'aborted'
        | 'project_resolution'
        | 'tool'
    message: string
    status?: number
    requestId?: string
    code?: string
    retryAfterMs?: number
    fields?: ApiFieldError[]
    body?: JsonValue
    projectResolution?: ProjectResolutionErrorDetails
}
