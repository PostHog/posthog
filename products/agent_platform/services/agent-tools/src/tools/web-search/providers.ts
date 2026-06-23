/**
 * Concrete web-search providers. Each maps one vendor's search API onto the
 * shared `WebSearchResult` shape and goes out through the injected
 * smokescreen-bound fetcher. Adding a provider = implement `WebSearchProvider`
 * and register it in `PROVIDER_FACTORIES` + `WEB_SEARCH_PROVIDER_NAMES`
 * (the latter lives in agent-shared alongside the interface).
 *
 * SSRF is enforced at the egress hop by smokescreen (RFC1918 / loopback /
 * cloud IMDS denial); vendor hosts are public Internet and need no
 * per-host allowlist entry.
 */

import type {
    HttpFetcher,
    WebSearchInput,
    WebSearchProvider,
    WebSearchProviderName,
    WebSearchResult,
} from '@posthog/agent-shared'

/** Cap each snippet so a chatty provider can't blow up the model's context. */
const MAX_SNIPPET = 2_000

function clip(s: string | undefined): string {
    return (s ?? '').slice(0, MAX_SNIPPET)
}

/** Extract a `results` array from a possibly-null/non-object JSON body. */
function asResults<T>(data: unknown, pick: (d: Record<string, unknown>) => T[] | undefined): T[] {
    if (data === null || typeof data !== 'object') {
        return []
    }
    return pick(data as Record<string, unknown>) ?? []
}

/** Exa — neural+keyword search built for retrieval. `highlights` are the LLM-relevant snippets.
 *
 * `#apiKey` (ECMAScript private name, not TS `private`) keeps the key off
 * the enumerable surface — `JSON.stringify(provider)` returns `{"name":"exa"}`,
 * so a stray debug dump / pino-serialized error context can't leak it. */
export class ExaProvider implements WebSearchProvider {
    readonly name = 'exa' as const
    readonly #apiKey: string
    constructor(apiKey: string) {
        this.#apiKey = apiKey
    }

    async search(input: WebSearchInput, http: HttpFetcher): Promise<WebSearchResult[]> {
        const res = await http.fetch('https://api.exa.ai/search', {
            method: 'POST',
            headers: { 'content-type': 'application/json', 'x-api-key': this.#apiKey },
            body: JSON.stringify({
                query: input.query,
                numResults: input.limit,
                contents: { highlights: true },
            }),
        })
        if (!res.ok) {
            throw new Error(`exa_http_${res.status}`)
        }
        const data: unknown = await res.json()
        const results = asResults<{ title?: string; url?: string; highlights?: string[]; text?: string }>(
            data,
            (d) =>
                d.results as Array<{ title?: string; url?: string; highlights?: string[]; text?: string }> | undefined
        )
        return results.map((r) => ({
            title: r.title ?? '',
            url: r.url ?? '',
            // Filter empty highlight spans first — `['','']`.join(' … ') is `' … '` (truthy),
            // which would otherwise suppress the `|| r.text` fallback and surface useless ellipses.
            snippet: clip(r.highlights?.filter(Boolean).join(' … ') || r.text),
        }))
    }
}

/** Tavily — agent-oriented search API; `content` is a short description per result. */
export class TavilyProvider implements WebSearchProvider {
    readonly name = 'tavily' as const
    readonly #apiKey: string
    constructor(apiKey: string) {
        this.#apiKey = apiKey
    }

    async search(input: WebSearchInput, http: HttpFetcher): Promise<WebSearchResult[]> {
        const res = await http.fetch('https://api.tavily.com/search', {
            method: 'POST',
            headers: { 'content-type': 'application/json', authorization: `Bearer ${this.#apiKey}` },
            body: JSON.stringify({
                query: input.query,
                max_results: input.limit,
                search_depth: 'basic',
            }),
        })
        if (!res.ok) {
            throw new Error(`tavily_http_${res.status}`)
        }
        const data: unknown = await res.json()
        const results = asResults<{ title?: string; url?: string; content?: string }>(
            data,
            (d) => d.results as Array<{ title?: string; url?: string; content?: string }> | undefined
        )
        return results.map((r) => ({
            title: r.title ?? '',
            url: r.url ?? '',
            snippet: clip(r.content),
        }))
    }
}

/** Brave — independent web index; `description` is the snippet, results under `web.results`. */
export class BraveProvider implements WebSearchProvider {
    readonly name = 'brave' as const
    readonly #apiKey: string
    constructor(apiKey: string) {
        this.#apiKey = apiKey
    }

    async search(input: WebSearchInput, http: HttpFetcher): Promise<WebSearchResult[]> {
        const url = new URL('https://api.search.brave.com/res/v1/web/search')
        url.searchParams.set('q', input.query)
        url.searchParams.set('count', String(input.limit))
        const res = await http.fetch(url.toString(), {
            method: 'GET',
            headers: { accept: 'application/json', 'x-subscription-token': this.#apiKey },
        })
        if (!res.ok) {
            throw new Error(`brave_http_${res.status}`)
        }
        const data: unknown = await res.json()
        const results = asResults<{ title?: string; url?: string; description?: string }>(data, (d) => {
            const web = d.web
            if (web === null || typeof web !== 'object') {
                return undefined
            }
            return (web as { results?: Array<{ title?: string; url?: string; description?: string }> }).results
        })
        return results.map((r) => ({
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
