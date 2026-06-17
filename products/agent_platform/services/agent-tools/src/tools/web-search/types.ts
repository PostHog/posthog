import type { HttpFetcher } from '@posthog/agent-shared'

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
