/**
 * Provider chain + the boot-time seam for `@posthog/web-search`.
 *
 * The runner builds the ordered chain from config at startup
 * (`buildWebSearchProviders`) and installs it via `setWebSearchProviders`.
 * The tool reads it through `getWebSearchProviders` and runs
 * `searchWithFallback` — primary first, each listed fallback next, trying the
 * following provider whenever one errors. This is the fix for the old dead
 * tool: it was registered but its provider was only ever set in tests, so it
 * always threw in prod. Now it's wired at boot and gated out of the session
 * tool surface when nothing is configured (see `webSearchConfigured` +
 * `buildAgentTools`).
 */

import type { HttpFetcher } from '@posthog/agent-shared'

import { PROVIDER_FACTORIES } from './providers'
import {
    type WebSearchInput,
    type WebSearchProvider,
    type WebSearchProviderName,
    type WebSearchResult,
    WEB_SEARCH_PROVIDER_NAMES,
} from './types'

// Set once at runner boot. Empty until then — the tool is filtered out of a
// session's tools while empty, so the model never sees a tool that just throws.
let PROVIDERS: WebSearchProvider[] = []

export function setWebSearchProviders(providers: WebSearchProvider[]): void {
    PROVIDERS = providers
}

export function getWebSearchProviders(): readonly WebSearchProvider[] {
    return PROVIDERS
}

export function webSearchConfigured(): boolean {
    return PROVIDERS.length > 0
}

export interface WebSearchProviderConfig {
    /** Primary provider id (AGENT_WEB_SEARCH_PROVIDER). Tried first. */
    primary?: string
    /**
     * Ordered fallback provider ids (AGENT_WEB_SEARCH_FALLBACKS, comma-separated),
     * tried after the primary. Empty → every other provider that has a key acts
     * as a fallback (natural order).
     */
    fallbacks?: string
    /** Per-provider API keys — a provider is usable only when its key is set. */
    keys: Partial<Record<WebSearchProviderName, string | undefined>>
}

function isProviderName(n: string): n is WebSearchProviderName {
    return (WEB_SEARCH_PROVIDER_NAMES as readonly string[]).includes(n)
}

/**
 * Resolve config into an ordered, de-duplicated chain of constructed providers.
 * Only providers with a configured key are included, so an unset primary is
 * skipped rather than fatal and the chain reflects exactly what can run.
 */
export function buildWebSearchProviders(cfg: WebSearchProviderConfig): WebSearchProvider[] {
    const order: string[] = []
    const push = (name?: string): void => {
        const n = name?.trim().toLowerCase()
        if (n && !order.includes(n)) {
            order.push(n)
        }
    }

    push(cfg.primary)
    const explicitFallbacks = (cfg.fallbacks ?? '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    if (explicitFallbacks.length > 0) {
        for (const f of explicitFallbacks) {
            push(f)
        }
    } else {
        // No explicit fallbacks → any other keyed provider is a last-resort fallback.
        for (const n of WEB_SEARCH_PROVIDER_NAMES) {
            push(n)
        }
    }

    const chain: WebSearchProvider[] = []
    for (const name of order) {
        if (!isProviderName(name)) {
            continue
        }
        const key = cfg.keys[name]
        if (!key) {
            continue
        }
        chain.push(PROVIDER_FACTORIES[name](key))
    }
    return chain
}

export interface WebSearchOutcome {
    results: WebSearchResult[]
    /** Which provider actually served the results. */
    provider: WebSearchProviderName
}

type ToolLog = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void

/**
 * Try each provider in order, returning the first success. A provider that
 * throws (HTTP error / network / parse) is logged and the next is tried.
 * Throws only when nothing is configured or every provider failed.
 */
export async function searchWithFallback(
    providers: readonly WebSearchProvider[],
    input: WebSearchInput,
    http: HttpFetcher,
    log: ToolLog
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
