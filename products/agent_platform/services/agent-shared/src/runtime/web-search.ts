/**
 * Web-search abstraction shared across the platform.
 *
 * The contract lives here (not in agent-tools) because `ToolContext` carries
 * the resolved provider chain — `@posthog/web-search` reads it the same way the
 * memory tools read `ToolContext.memoryStore`. The runner builds the chain from
 * config at boot (`buildWebSearchProviders` in agent-tools) and injects it
 * through `WorkerDeps → AgentToolDeps → ToolContext.webSearchProviders`; there
 * is no module singleton (see agent-shared rule 5).
 *
 * Concrete vendor providers (Exa / Tavily / Brave) implement `WebSearchProvider`
 * in agent-tools. `searchWithFallback` is the order-and-retry runner the tool
 * calls.
 */

import type { HttpFetcher } from './http-client'

/** One normalized search hit, identical across providers. */
export interface WebSearchResult {
    title: string
    url: string
    snippet: string
}

export interface WebSearchInput {
    query: string
    /** Max results to return (already clamped by the tool schema). */
    limit: number
}

/** Provider ids referenced by config (primary / fallbacks) and logs. */
export const WEB_SEARCH_PROVIDER_NAMES = ['exa', 'tavily', 'brave'] as const
export type WebSearchProviderName = (typeof WEB_SEARCH_PROVIDER_NAMES)[number]

/**
 * A web-search backend. Construction takes the provider's API key; `search`
 * takes the per-call smokescreen-bound fetcher (the tool passes `ctx.http`) —
 * egress MUST go through it, never a bare `fetch`, so the proxy enforces SSRF
 * at the egress hop like every other tool.
 */
export interface WebSearchProvider {
    readonly name: WebSearchProviderName
    search(input: WebSearchInput, http: HttpFetcher): Promise<WebSearchResult[]>
}

export interface WebSearchOutcome {
    results: WebSearchResult[]
    /** Which provider actually served the results. */
    provider: WebSearchProviderName
}

/** Logger shape compatible with `ToolContext.log`. */
type WebSearchLog = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void

/**
 * Try each provider in order, returning the first success. A provider that
 * throws (HTTP error / network / parse) is logged and the next is tried.
 * Throws only when nothing is configured or every provider failed.
 */
export async function searchWithFallback(
    providers: readonly WebSearchProvider[],
    input: WebSearchInput,
    http: HttpFetcher,
    log: WebSearchLog
): Promise<WebSearchOutcome> {
    if (providers.length === 0) {
        throw new Error('web_search_not_configured')
    }
    const errors: string[] = []
    for (const provider of providers) {
        try {
            const results = await provider.search(input, http)
            return { results, provider: provider.name }
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err)
            errors.push(`${provider.name}: ${message}`)
            log('warn', 'web_search.provider_failed', { provider: provider.name, error: message })
        }
    }
    throw new Error(`web_search_all_providers_failed: ${errors.join('; ')}`)
}
