/**
 * Config → provider-chain resolution for `@posthog/web-search`.
 *
 * The runner calls `buildWebSearchProviders` once at boot, then injects the
 * resulting chain through `WorkerDeps → AgentToolDeps → ToolContext.webSearchProviders`.
 * There is no module singleton (agent-shared rule 5): the chain is plain data
 * threaded down with everything else. When the chain is empty the tool is gated
 * out of the session surface (`buildAgentTools`), so the model never sees a tool
 * that just throws.
 *
 * `searchWithFallback` (the order-and-retry runner the tool calls) lives in
 * agent-shared next to the `WebSearchProvider` interface.
 */

import { type WebSearchProvider, type WebSearchProviderName, WEB_SEARCH_PROVIDER_NAMES } from '@posthog/agent-shared'

import { PROVIDER_FACTORIES } from './providers'

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
