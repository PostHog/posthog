/**
 * HTTP clients for the ai-gateway's read-side endpoints.
 *
 *   GET /v1/usage/{request_id} — settled cost + token breakdown per request
 *   GET /v1/wallet/balance     — team prepaid balance + pending hold
 *
 * Both endpoints take the same `phc_` bearer the data plane does (resolved
 * per-team via `TeamApiKeyResolver`).
 */

import type { HttpFetcher } from './http-client'
import { createLogger } from './logger'

/** Wire shape of GET /v1/usage/{request_id}. */
export interface GatewayUsage {
    request_id: string
    team_id: number
    model?: string
    provider?: string
    input_tokens?: number
    output_tokens?: number
    /** USD as decimal string — parse to number when consuming. */
    cost_usd: string
    list_cost_usd?: string
    distinct_id?: string
    settled_at: string
}

/** Wire shape of GET /v1/wallet/balance. */
export interface GatewayWalletBalance {
    team_id: number
    /** USD as decimal string — parse to number when consuming. */
    available_usd: string
    pending_usd: string
    currency: string
}

export interface GatewayClient {
    /**
     * Returns the settled cost for a previously-dispatched request, or
     * `null` if the settle hasn't landed yet / the row belongs to another
     * team / the request was never settled. Callers retry on null up to
     * the gateway's settlement window.
     */
    getUsage(requestId: string, opts: { phc: string }): Promise<GatewayUsage | null>
    /** Returns the team's prepaid balance + pending hold. */
    getWalletBalance(opts: { phc: string }): Promise<GatewayWalletBalance>
}

export interface HttpGatewayClientOpts {
    /** Gateway base URL (e.g. http://localhost:8080/v1). */
    baseUrl: string
    /** Per-request timeout in ms. Default 3000. */
    timeoutMs?: number
    /**
     * For getUsage: max attempts including the first. After every 404 the
     * client backs off and re-fetches up to `maxAttempts` times — covers
     * the small window between the gateway's stream-close and its deferred
     * Settle landing in the ledger. Default 4.
     */
    maxAttempts?: number
    /** Initial backoff for the retry loop in ms. Default 25. Doubles each retry. */
    initialBackoffMs?: number
    /**
     * Outbound HTTP. Wired at the runner entrypoint with a
     * `DirectHttpClient` instance — ai-gateway is cluster-internal and
     * smokescreen would deny the call as RFC1918. **Never pass the
     * proxy-bound `HttpClient` here**: a smokescreen rejection would
     * silently drop cost-capture data with only a warn in the logs.
     */
    http: HttpFetcher
}

export class HttpGatewayClient implements GatewayClient {
    private readonly log = createLogger('gateway-client')
    private readonly baseUrl: string
    private readonly timeoutMs: number
    private readonly maxAttempts: number
    private readonly initialBackoffMs: number
    private readonly http: HttpFetcher

    constructor(opts: HttpGatewayClientOpts) {
        this.baseUrl = opts.baseUrl.replace(/\/$/, '')
        this.timeoutMs = opts.timeoutMs ?? 3_000
        this.maxAttempts = Math.max(1, opts.maxAttempts ?? 4)
        this.initialBackoffMs = Math.max(1, opts.initialBackoffMs ?? 25)
        this.http = opts.http
    }

    async getUsage(requestId: string, opts: { phc: string }): Promise<GatewayUsage | null> {
        // Settle on the gateway is deferred — it fires *after* the stream
        // handler returns and the client has already seen [DONE]. There's a
        // small window where the runner can ask before the debit row exists.
        // Retry on 404 with exponential backoff; bail on any non-404 error.
        let backoff = this.initialBackoffMs
        for (let attempt = 1; attempt <= this.maxAttempts; attempt++) {
            // Don't URL-encode the request_id: chi's path-param matcher
            // returns the raw escaped segment, so encoding colons as %3A
            // makes the lookup miss against ledger rows whose reference_id
            // contains literal colons. Our id format (`agent:<uuid>:<turn>`)
            // is path-safe — only `:` and hex with dashes.
            const res = await this.fetchJson(`/usage/${requestId}`, opts.phc)
            if (res.kind === 'ok') {
                return res.body as GatewayUsage
            }
            if (res.kind === 'not_found' && attempt < this.maxAttempts) {
                await sleep(backoff)
                backoff *= 2
                continue
            }
            if (res.kind === 'not_found') {
                this.log.debug({ requestId, attempts: attempt }, 'gateway.usage.miss')
                return null
            }
            // Any other error (auth, 5xx, network): give up — caller treats
            // as missing and the session's usage_total just lacks this turn's
            // cost. Not silent: log a warn so on-call sees a pattern.
            this.log.warn({ requestId, status: res.status, err: res.err }, 'gateway.usage.fetch_failed')
            return null
        }
        return null
    }

    async getWalletBalance(opts: { phc: string }): Promise<GatewayWalletBalance> {
        const res = await this.fetchJson('/wallet/balance', opts.phc)
        if (res.kind === 'ok') {
            return res.body as GatewayWalletBalance
        }
        throw new Error(
            `gateway: wallet balance fetch failed (status=${'status' in res ? res.status : '?'}, err=${'err' in res ? res.err : ''})`
        )
    }

    private async fetchJson(
        path: string,
        phc: string
    ): Promise<
        { kind: 'ok'; body: unknown } | { kind: 'not_found' } | { kind: 'error'; status?: number; err?: string }
    > {
        const ac = new AbortController()
        const timer = setTimeout(() => ac.abort(), this.timeoutMs)
        try {
            const res = await this.http.fetch(`${this.baseUrl}${path}`, {
                headers: { Authorization: `Bearer ${phc}` },
                signal: ac.signal,
            })
            if (res.status === 200) {
                const body = await res.json()
                return { kind: 'ok', body }
            }
            if (res.status === 404) {
                // Drain the body so the connection can be reused. Ignore errors.
                await res.text().catch(() => undefined)
                return { kind: 'not_found' }
            }
            const errText = await res.text().catch(() => '')
            return { kind: 'error', status: res.status, err: errText }
        } catch (err) {
            return { kind: 'error', err: (err as Error).message }
        } finally {
            clearTimeout(timer)
        }
    }
}

function sleep(ms: number): Promise<void> {
    return new Promise((res) => setTimeout(res, ms))
}
