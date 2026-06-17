/**
 * Concrete web-search providers. Each maps one vendor's search API onto the
 * shared `WebSearchResult` shape and goes out through the injected
 * smokescreen-bound fetcher. Adding a provider = implement `WebSearchProvider`
 * and register it in `PROVIDER_FACTORIES` + `WEB_SEARCH_PROVIDER_NAMES`.
 *
 * The vendor host of every provider must be on the smokescreen allowlist
 * (charts/shared/agent-platform) or egress is denied in prod.
 */

import type { HttpFetcher } from '@posthog/agent-shared'

import type { WebSearchInput, WebSearchProvider, WebSearchProviderName, WebSearchResult } from './types'

/** Cap each snippet so a chatty provider can't blow up the model's context. */
const MAX_SNIPPET = 2_000

function clip(s: string | undefined): string {
    const v = s ?? ''
    return v.length > MAX_SNIPPET ? v.slice(0, MAX_SNIPPET) : v
}

/** Exa — neural+keyword search built for retrieval. `highlights` are the LLM-relevant snippets. */
export class ExaProvider implements WebSearchProvider {
    readonly name = 'exa' as const
    constructor(private readonly apiKey: string) {}

    async search(input: WebSearchInput, http: HttpFetcher): Promise<WebSearchResult[]> {
        const res = await http.fetch('https://api.exa.ai/search', {
            method: 'POST',
            headers: { 'content-type': 'application/json', 'x-api-key': this.apiKey },
            body: JSON.stringify({
                query: input.query,
                numResults: input.limit,
                contents: { highlights: true },
            }),
        })
        if (!res.ok) {
            throw new Error(`exa_http_${res.status}`)
        }
        const data = (await res.json()) as {
            results?: Array<{ title?: string; url?: string; highlights?: string[]; text?: string }>
        }
        return (data.results ?? []).map((r) => ({
            title: r.title ?? '',
            url: r.url ?? '',
            snippet: clip(r.highlights?.join(' … ') || r.text),
        }))
    }
}

/** Tavily — agent-oriented search API; `content` is a short description per result. */
export class TavilyProvider implements WebSearchProvider {
    readonly name = 'tavily' as const
    constructor(private readonly apiKey: string) {}

    async search(input: WebSearchInput, http: HttpFetcher): Promise<WebSearchResult[]> {
        const res = await http.fetch('https://api.tavily.com/search', {
            method: 'POST',
            headers: { 'content-type': 'application/json', authorization: `Bearer ${this.apiKey}` },
            body: JSON.stringify({
                query: input.query,
                max_results: input.limit,
                search_depth: 'basic',
            }),
        })
        if (!res.ok) {
            throw new Error(`tavily_http_${res.status}`)
        }
        const data = (await res.json()) as {
            results?: Array<{ title?: string; url?: string; content?: string }>
        }
        return (data.results ?? []).map((r) => ({
            title: r.title ?? '',
            url: r.url ?? '',
            snippet: clip(r.content),
        }))
    }
}

/** Brave — independent web index; `description` is the snippet, results under `web.results`. */
export class BraveProvider implements WebSearchProvider {
    readonly name = 'brave' as const
    constructor(private readonly apiKey: string) {}

    async search(input: WebSearchInput, http: HttpFetcher): Promise<WebSearchResult[]> {
        const url = new URL('https://api.search.brave.com/res/v1/web/search')
        url.searchParams.set('q', input.query)
        url.searchParams.set('count', String(input.limit))
        const res = await http.fetch(url.toString(), {
            method: 'GET',
            headers: { accept: 'application/json', 'x-subscription-token': this.apiKey },
        })
        if (!res.ok) {
            throw new Error(`brave_http_${res.status}`)
        }
        const data = (await res.json()) as {
            web?: { results?: Array<{ title?: string; url?: string; description?: string }> }
        }
        return (data.web?.results ?? []).map((r) => ({
            title: r.title ?? '',
            url: r.url ?? '',
            snippet: clip(r.description),
        }))
    }
}

/** name → constructor. The single place to wire a new provider's key in. */
export const PROVIDER_FACTORIES: Record<WebSearchProviderName, (apiKey: string) => WebSearchProvider> = {
    exa: (apiKey) => new ExaProvider(apiKey),
    tavily: (apiKey) => new TavilyProvider(apiKey),
    brave: (apiKey) => new BraveProvider(apiKey),
}
