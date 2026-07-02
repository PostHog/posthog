// Client configuration and environment resolution.

/** Injectable fetch implementation. Matches the global `fetch` signature. */
export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

export interface ClientConfig {
    /** Personal API key (`phx_…`), project secret key (`phs_…`), or bearer token. */
    apiKey: string
    /** API base URL. Default: `https://us.posthog.com`. */
    host: string
    /** Default project id for project-scoped calls. Lazily resolved when omitted. */
    projectId?: string | number | undefined
    /** Default organization id for org-scoped calls. Lazily resolved when omitted. */
    organizationId?: string | undefined
    /** Transport override (proxies, tests, sandboxes). Defaults to global `fetch`. */
    fetch?: FetchLike | undefined
    /** Extra headers attached to every request. */
    headers?: Record<string, string> | undefined
}

export interface CreateClientOptions {
    apiKey?: string
    host?: string
    projectId?: string | number
    organizationId?: string
    fetch?: FetchLike
    headers?: Record<string, string>
}

/** Per-call overrides available on every generated resource method. */
export interface RequestOptions {
    /** Override the project id for this call. */
    projectId?: string | number
    /** Override the organization id for this call. */
    organizationId?: string
    /** Abort signal forwarded to the underlying fetch. */
    signal?: AbortSignal
    /** Extra headers merged into this request. */
    headers?: Record<string, string>
}

export const DEFAULT_HOST = 'https://us.posthog.com'

/**
 * Reads an environment variable without assuming `process` exists (browser,
 * some workers). Returns undefined when the platform has no `process.env`.
 */
export function readEnv(name: string): string | undefined {
    const proc = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
    const value = proc?.env?.[name]
    return value && value.length > 0 ? value : undefined
}

/**
 * Resolves client config from the environment. Never throws — a missing key
 * yields `apiKey: undefined`, so the caller can surface `MissingApiKeyError`
 * only when a request is actually attempted (keeps import-time side effects out
 * of browser bundles).
 */
export function resolveConfigFromEnv(): {
    apiKey: string | undefined
    host: string
    projectId: string | undefined
    organizationId: string | undefined
} {
    return {
        apiKey: readEnv('POSTHOG_API_KEY'),
        host: readEnv('POSTHOG_HOST') ?? DEFAULT_HOST,
        projectId: readEnv('POSTHOG_PROJECT_ID'),
        organizationId: readEnv('POSTHOG_ORGANIZATION_ID'),
    }
}

/** Strips a trailing slash so path concatenation never doubles up. */
export function normalizeHost(host: string): string {
    return host.replace(/\/+$/, '')
}
