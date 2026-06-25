/**
 * HTTP clients for the agent platform.
 *
 * Two classes, deliberately separate:
 *
 *   - **`HttpClient`** — the proxy-bound default. Every outbound fetch
 *     reachable from agent author code (native tools, MCP transport, the
 *     in-process sandbox guest, the Slack identity bridge) goes through
 *     this. In prod its dispatcher is smokescreen (SSRF enforcement); in
 *     dev/test it's unset and requests go direct.
 *
 *   - **`DirectHttpClient`** — no proxy, ever. Reserved for cluster-
 *     internal services the platform owns and calls itself (ai-gateway,
 *     in-cluster PostHog API). The class divide is the capability gate:
 *     `ToolContext.http` is typed `HttpFetcher` and only ever holds a
 *     proxy-bound `HttpClient`, so an agent author cannot reach the
 *     direct path by guessing an internal hostname. A NO_PROXY-style env
 *     allowlist would defeat this — an `@posthog/http-request` against
 *     `posthog-web-django.posthog.svc.cluster.local` would match the
 *     suffix and bypass smokescreen entirely.
 *
 * Both wrap `undici.fetch` and apply a default 30s timeout when the
 * caller doesn't supply a signal. Node's built-in `fetch` does **not**
 * read HTTP_PROXY / HTTPS_PROXY env vars on its own — that's why every
 * agent-platform outbound call must go through one of these classes
 * rather than calling `fetch` directly. The oxlint rule in
 * `.oxlintrc.json` enforces that for the agent-* `src/` trees.
 *
 * Tests substitute `ctx.http` with a `vi.fn()` mock at the seam (the
 * structural `HttpFetcher` type below makes that a one-liner — no
 * separate fake class).
 */

import { ProxyAgent, fetch as undiciFetch, type Dispatcher } from 'undici'

/** Structural type for `ToolContext.http` — anything with a fetch method. */
export interface HttpFetcher {
    fetch: (input: string | URL, init?: RequestInit) => Promise<Response>
}

export interface HttpClientOptions {
    /**
     * Proxy URL. In prod, set to the smokescreen URL (see
     * `charts/shared/agent-platform/common.yaml` `httpProxy.enabled`).
     * Unset in dev / harness — requests go direct.
     */
    proxyUrl?: string
    /** Per-request timeout when the caller didn't supply a signal. Default 30s. */
    defaultTimeoutMs?: number
}

const DEFAULT_TIMEOUT_MS = 30_000

/**
 * Proxy-bound HTTP client. Wired everywhere agent author code can
 * influence the outbound URL (tools, MCP, sandbox guest, Slack identity
 * bridge → slack.com). Never use this for cluster-internal services —
 * smokescreen denies RFC1918 by design.
 */
export class HttpClient implements HttpFetcher {
    private readonly dispatcher: Dispatcher | undefined
    private readonly defaultTimeoutMs: number

    constructor(opts: HttpClientOptions = {}) {
        this.dispatcher = opts.proxyUrl ? new ProxyAgent(opts.proxyUrl) : undefined
        this.defaultTimeoutMs = opts.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS
    }

    async fetch(input: string | URL, init?: RequestInit): Promise<Response> {
        return runFetch(input, init, this.dispatcher, this.defaultTimeoutMs)
    }
}

export interface DirectHttpClientOptions {
    /** Per-request timeout when the caller didn't supply a signal. Default 30s. */
    defaultTimeoutMs?: number
}

/**
 * Direct HTTP — no proxy dispatcher, no allowlist, no escape hatch.
 *
 * Wire ONLY at platform-internal call sites (`HttpGatewayClient`,
 * `defaultPosthogIntrospector`) where the target URL is set in chart
 * config, not by an agent author. Never thread this onto `ToolContext`,
 * `WorkerDeps`, or anywhere agent code can reach.
 */
export class DirectHttpClient implements HttpFetcher {
    private readonly defaultTimeoutMs: number

    constructor(opts: DirectHttpClientOptions = {}) {
        this.defaultTimeoutMs = opts.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS
    }

    async fetch(input: string | URL, init?: RequestInit): Promise<Response> {
        return runFetch(input, init, undefined, this.defaultTimeoutMs)
    }
}

function runFetch(
    input: string | URL,
    init: RequestInit | undefined,
    dispatcher: Dispatcher | undefined,
    defaultTimeoutMs: number
): Promise<Response> {
    const signal = init?.signal ?? AbortSignal.timeout(defaultTimeoutMs)
    // undici's RequestInit accepts a `dispatcher` field that the global
    // fetch types don't expose; the merged object only conforms to
    // undici's shape, hence the `unknown` step. The runtime fetch is
    // still undici under the hood, so the call is correct.
    const merged = { ...init, signal, dispatcher } as unknown as Parameters<typeof undiciFetch>[1]
    return undiciFetch(input, merged) as unknown as Promise<Response>
}
