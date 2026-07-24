// Typed errors mirroring the PostHog API error contract. Ported from
// services/mcp/src/lib/errors.ts, trimmed to the transport-level concerns the
// SDK needs (no MCP tool-result formatting, no analytics capture).

export interface PostHogApiErrorOptions {
    status: number
    statusText: string
    body: string
    url: string
    method: string
    message?: string
}

/**
 * Thrown when the PostHog API rejects a request with a non-success status that
 * isn't already handled by a more specific subclass. Carries the status code so
 * callers can distinguish recoverable input errors (4xx) from service failures (5xx).
 */
export class PostHogApiError extends Error {
    public readonly status: number
    public readonly statusText: string
    public readonly body: string
    public readonly url: string
    public readonly method: string

    constructor(options: PostHogApiErrorOptions) {
        super(options.message ?? buildDefaultApiErrorMessage(options))
        this.name = 'PostHogApiError'
        this.status = options.status
        this.statusText = options.statusText
        this.body = options.body
        this.url = options.url
        this.method = options.method
    }
}

function buildDefaultApiErrorMessage(options: PostHogApiErrorOptions): string {
    return `Request failed:\nURL: ${options.method} ${options.url}\nStatus Code: ${options.status} (${options.statusText})\nError Message: ${options.body}`
}

export interface PostHogValidationErrorOptions {
    detail: string
    attr: string | undefined
    code: string | undefined
    extra: Record<string, unknown> | undefined
    url: string
    method: string
}

/**
 * Thrown when the PostHog API rejects a request with a `validation_error` body.
 * Carries the structured `extra` payload (if any) so callers can surface
 * information that doesn't fit in a single `detail` line.
 */
export class PostHogValidationError extends Error {
    public readonly detail: string
    public readonly attr: string | undefined
    public readonly code: string | undefined
    public readonly extra: Record<string, unknown> | undefined
    public readonly url: string
    public readonly method: string

    constructor(options: PostHogValidationErrorOptions) {
        const attr = options.attr ? ` (field: ${options.attr})` : ''
        super(`Validation error: ${options.detail}${attr}`)
        this.name = 'PostHogValidationError'
        this.detail = options.detail
        this.attr = options.attr
        this.code = options.code
        this.extra = options.extra
        this.url = options.url
        this.method = options.method
    }
}

export interface PostHogPermissionErrorOptions {
    detail: string
    missingScope?: string | undefined
    url: string
    method: string
}

/**
 * Thrown when the PostHog API rejects a request with HTTP 403 `permission_denied`.
 * Preserves the missing scope (when present) so callers can surface an actionable
 * remediation message.
 */
export class PostHogPermissionError extends Error {
    public readonly detail: string
    public readonly missingScope: string | undefined
    public readonly url: string
    public readonly method: string

    constructor(options: PostHogPermissionErrorOptions) {
        const message = options.missingScope
            ? `Missing PostHog API scope: '${options.missingScope}'`
            : `PostHog API permission denied: ${options.detail}`
        super(message)
        this.name = 'PostHogPermissionError'
        this.detail = options.detail
        this.missingScope = options.missingScope
        this.url = options.url
        this.method = options.method
    }
}

export interface PostHogRateLimitErrorOptions {
    body: string
    url: string
    method: string
    retryAfterSeconds: number | null
}

/**
 * Thrown when the PostHog API responds with HTTP 429 and the retry budget is
 * exhausted. Carries the server's Retry-After hint (when present) so callers can
 * decide when to retry.
 */
export class PostHogRateLimitError extends PostHogApiError {
    public readonly retryAfterSeconds: number | null

    constructor(options: PostHogRateLimitErrorOptions) {
        const retryHint = options.retryAfterSeconds !== null ? ` Retry after ${options.retryAfterSeconds} seconds.` : ''
        super({
            status: 429,
            statusText: 'Too Many Requests',
            body: options.body,
            url: options.url,
            method: options.method,
            message: `PostHog API rate limit exceeded (429) on ${options.method} ${options.url}.${retryHint}`,
        })
        this.name = 'PostHogRateLimitError'
        this.retryAfterSeconds = options.retryAfterSeconds
    }
}

/**
 * Thrown when no API key can be resolved for the default client. Names the env
 * vars so the caller knows exactly what to set.
 */
export class MissingApiKeyError extends Error {
    constructor() {
        super(
            'No PostHog API key configured. Set the POSTHOG_API_KEY environment variable, or ' +
                "call createClient({ apiKey }) explicitly. Optional companions: POSTHOG_HOST (default 'https://us.posthog.com'), " +
                'POSTHOG_PROJECT_ID, POSTHOG_ORGANIZATION_ID.'
        )
        this.name = 'MissingApiKeyError'
    }
}

/**
 * Thrown when a request needs a project id but none was configured and it could
 * not be resolved from `GET /api/users/@me/`.
 */
export class MissingProjectError extends Error {
    constructor(detail?: string) {
        super(
            'Could not resolve a PostHog project id. Pass `projectId` to createClient(), set POSTHOG_PROJECT_ID, ' +
                'or provide `projectId` in the per-call options.' +
                (detail ? ` (${detail})` : '')
        )
        this.name = 'MissingProjectError'
    }
}

/**
 * Thrown when a request needs an organization id but none was configured and it
 * could not be resolved from `GET /api/users/@me/`.
 */
export class MissingOrganizationError extends Error {
    constructor(detail?: string) {
        super(
            'Could not resolve a PostHog organization id. Pass `organizationId` to createClient(), set ' +
                'POSTHOG_ORGANIZATION_ID, or provide `organizationId` in the per-call options.' +
                (detail ? ` (${detail})` : '')
        )
        this.name = 'MissingOrganizationError'
    }
}

/**
 * Parses a Retry-After header into whole seconds. Returns null for missing
 * headers, HTTP-date values, and bogus negatives.
 */
export function parseRetryAfterSeconds(header: string | null): number | null {
    if (!header) {
        return null
    }
    const seconds = Number.parseInt(header, 10)
    return Number.isNaN(seconds) || seconds < 0 ? null : seconds
}
