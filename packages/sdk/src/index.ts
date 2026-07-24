// @posthog/sdk — TypeScript SDK for the PostHog management API.
//
// The resource layer under `src/generated/` is emitted by `scripts/generate.ts`
// from the committed MCP codegen artifacts; the transport core under `src/core/`
// is handwritten. See README.md.

import {
    type CreateClientOptions,
    DEFAULT_HOST,
    type FetchLike,
    type RequestOptions,
    resolveConfigFromEnv,
} from './core/config'
import { MissingApiKeyError } from './core/errors'
import { HttpClient } from './core/http'
import { ScopeResolver } from './core/scope'
import { PostHogClient } from './generated/client'

export { PostHogClient } from './generated/client'
export type { CreateClientOptions, FetchLike, RequestOptions } from './core/config'
export {
    MissingApiKeyError,
    MissingOrganizationError,
    MissingProjectError,
    PostHogApiError,
    PostHogPermissionError,
    PostHogRateLimitError,
    PostHogValidationError,
} from './core/errors'
export type { HttpClient } from './core/http'
export type { QueryNode, QueryResponse } from './core/query'
// Response types for `client.query.*`, derived from frontend/src/queries/schema.json.
export type * from './generated/query-responses'
export type { Schemas } from './generated/schemas'

/**
 * Create an explicitly-configured PostHog client.
 *
 * @example
 * const ph = createClient({ apiKey: 'phx_…', host: 'https://eu.posthog.com', projectId: 123 })
 * await ph.featureFlags.list()
 */
export function createClient(options: CreateClientOptions = {}): PostHogClient {
    const apiKey = options.apiKey ?? resolveConfigFromEnv().apiKey
    if (!apiKey) {
        throw new MissingApiKeyError()
    }
    const host = options.host ?? resolveConfigFromEnv().host ?? DEFAULT_HOST
    const http = new HttpClient({
        apiKey,
        host,
        fetch: options.fetch,
        headers: options.headers,
    })
    const scope = new ScopeResolver(http, {
        projectId: options.projectId,
        organizationId: options.organizationId,
    })
    return new PostHogClient(http, scope)
}

/**
 * Build the default client from environment variables. Called lazily by the
 * `client` proxy on first property access, so importing this package never reads
 * `process` (safe in the browser) and never throws until a method is invoked.
 */
function createDefaultClient(): PostHogClient {
    const env = resolveConfigFromEnv()
    if (!env.apiKey) {
        throw new MissingApiKeyError()
    }
    const fetchOverride = (globalThis as { fetch?: FetchLike }).fetch
    return createClient({
        apiKey: env.apiKey,
        host: env.host,
        projectId: env.projectId,
        organizationId: env.organizationId,
        ...(fetchOverride ? { fetch: fetchOverride.bind(globalThis) } : {}),
    })
}

/**
 * Lazy default client. Reads `POSTHOG_API_KEY` / `POSTHOG_HOST` /
 * `POSTHOG_PROJECT_ID` / `POSTHOG_ORGANIZATION_ID` on first method access — never
 * at import time. Missing key → `MissingApiKeyError` naming the env vars.
 *
 * @example
 * import { client } from '@posthog/sdk'
 * await client.featureFlags.list()
 */
export const client: PostHogClient = new Proxy({} as PostHogClient, {
    get(_target, prop, receiver) {
        const instance = getDefaultClient()
        const value = Reflect.get(instance, prop, receiver)
        return typeof value === 'function' ? value.bind(instance) : value
    },
    has(_target, prop) {
        return Reflect.has(getDefaultClient(), prop)
    },
})

let defaultClientInstance: PostHogClient | undefined
function getDefaultClient(): PostHogClient {
    defaultClientInstance ??= createDefaultClient()
    return defaultClientInstance
}
