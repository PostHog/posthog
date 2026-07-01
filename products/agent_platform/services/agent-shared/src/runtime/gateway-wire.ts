/**
 * Single-sourced runner ↔ ai-gateway wire contract. Every caller (usage/wallet
 * client, model catalog, runner dispatch) must agree on three facts, each of
 * which shipped as a bug when re-derived independently:
 *   - auth: the gateway reads only `Authorization: Bearer` (an `x-api-key`-only
 *     provider shape 401s).
 *   - settlement id: key the settled-cost lookup on the gateway's server-minted
 *     id, not a client-chosen one, or the `/usage` lookup 404s forever.
 *   - cost provenance: only a figure parsed from a `/usage` response is billed.
 */

import type { GatewayUsage } from './gateway-client'

/**
 * Every gateway surface authenticates the same way. Build the header through
 * this, not inline `Bearer ${token}`, so a provider's own wire shape can't
 * reintroduce the `x-api-key` 401.
 */
export function gatewayAuthHeader(token: string): { Authorization: string } {
    return { Authorization: `Bearer ${token}` }
}

/**
 * Response header carrying the gateway's server-minted settlement id (never the
 * caller's Idempotency-Key). Both dispatch and the settled-cost lookup import
 * this constant so they can't drift onto two ideas of "the request id".
 */
export const GATEWAY_REQUEST_ID_HEADER = 'x-request-id'

/**
 * Pull the gateway's settlement id off a dispatch response's headers.
 * Returns `undefined` when the gateway didn't stamp one (misroute, header
 * stripped by an intermediary) — callers must treat that as "skip the
 * settled-cost fetch for this turn", never fall back to a locally-chosen id.
 */
export function extractGatewayRequestId(headers: Record<string, string | undefined>): string | undefined {
    return headers[GATEWAY_REQUEST_ID_HEADER] || undefined
}

/**
 * Settled-usage lookup path. Takes the id from `extractGatewayRequestId` — never
 * a client-chosen id — so dispatch and lookup build the same URL.
 */
export function gatewayUsagePath(requestId: string): string {
    return `/usage/${requestId}`
}

/**
 * A provably gateway-settled cost — the only kind reportable as billed. The
 * `source: 'gateway'` literal blocks assigning a provider estimate without a
 * type error; only `gatewaySettledCost` produces one.
 */
export interface GatewaySettledCost {
    readonly source: 'gateway'
    readonly usd: number
}

/**
 * Parse a settled-usage response into a provenance-tagged cost. Returns
 * `null` on a non-finite wire value (NaN, empty string) — callers already
 * treat a failed/empty usage fetch as "this turn's cost stays unknown",
 * never as "fall back to an estimate".
 */
export function gatewaySettledCost(usage: Pick<GatewayUsage, 'cost_usd'>): GatewaySettledCost | null {
    const usd = Number(usage.cost_usd)
    return Number.isFinite(usd) ? { source: 'gateway', usd } : null
}

/**
 * The single point that decides whether a cost figure is allowed to reach
 * analytics. Throws on anything that isn't `source: 'gateway'` with a finite
 * `usd` — including a plausible-looking object that bypassed the type system
 * via a cast — so the pi-estimate-leak bug class can't come back through an
 * `as GatewaySettledCost`. Callers (the analytics sinks) catch around this
 * the same way they already catch-and-log capture failures, so a rejected
 * event is dropped, not fatal to the whole batch.
 */
export function assertGatewayProvenance(cost: { source?: unknown; usd?: unknown }): GatewaySettledCost {
    if (cost.source !== 'gateway' || typeof cost.usd !== 'number' || !Number.isFinite(cost.usd)) {
        throw new Error(`gateway-wire: refusing non-gateway cost provenance (source=${String(cost.source)})`)
    }
    return { source: 'gateway', usd: cost.usd }
}
