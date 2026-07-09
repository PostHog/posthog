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

import {
    type Logger,
    type WebSearchProvider,
    type WebSearchProviderName,
    WEB_SEARCH_PROVIDER_NAMES,
} from '@posthog/agent-shared'

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
    /** Per-provider API keys — a provider is usable only when its key is set.
     *  Non-partial Record so adding a new id to `WEB_SEARCH_PROVIDER_NAMES`
     *  forces every call site (notably agent-runner/src/index.ts) to wire a
     *  matching `<name>ApiKey` config field; missing it would otherwise
     *  silently drop the new provider from the chain. */
    keys: Record<WebSearchProviderName, string | undefined>
}

function isProviderName(n: string): n is WebSearchProviderName {
    return (WEB_SEARCH_PROVIDER_NAMES as readonly string[]).includes(n)
}

/**
 * Resolve config into an ordered, de-duplicated chain of constructed providers.
 * Only providers with a configured key are included, so an unset primary is
 * skipped rather than fatal and the chain reflects exactly what can run.
 *
 * An unrecognised name in `fallbacks` (the primary is enum-validated at config
 * load) is skipped with a `warn` so a misconfigured deployment is self-diagnosing
 * rather than silently running a shorter chain. A configured primary whose key
 * is missing emits its own `warn` for the same reason — the operator chose that
 * provider and silently falling through hides intent from `web_search.enabled`.
 */
export function buildWebSearchProviders(cfg: WebSearchProviderConfig, log?: Logger): WebSearchProvider[] {
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
    // Explicit list when given, otherwise every other keyed provider as a last-resort fallback.
    const fallbackSource = explicitFallbacks.length > 0 ? explicitFallbacks : WEB_SEARCH_PROVIDER_NAMES
    for (const n of fallbackSource) {
        push(n)
    }

    const primaryName = cfg.primary?.trim().toLowerCase()
    const chain: WebSearchProvider[] = []
    for (const name of order) {
        if (!isProviderName(name)) {
            log?.warn(
                { name, known: WEB_SEARCH_PROVIDER_NAMES },
                'web_search.unknown_provider — fallback id not recognised, skipping'
            )
            continue
        }
        // Trim once at construction so env vars with trailing whitespace / CRLF
        // (`EXA_API_KEY=…\n` from a poorly-templated secret) don't reach undici
        // as `Invalid character in header content` and don't pass `!key` only
        // to return blanket 401s from the vendor.
        const key = cfg.keys[name]?.trim()
        if (!key) {
            if (name === primaryName) {
                log?.warn(
                    { provider: name },
                    'web_search.primary_key_missing — configured primary has no API key, dropping'
                )
            }
            continue
        }
        chain.push(PROVIDER_FACTORIES[name](key))
    }
    return chain
}
