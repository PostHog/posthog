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
 * Safe charset for the settlement id before it's interpolated into the authed
 * `GET /v1/usage/{id}` path. Server-minted, so this is defense-in-depth: a `/`,
 * `?`, whitespace or control char must not reshape the URL.
 */
const GATEWAY_REQUEST_ID_PATTERN = /^[A-Za-z0-9._-]+$/

/**
 * Pull the gateway's settlement id off response headers. Returns `undefined` if
 * absent or failing the charset check — callers must skip the settled-cost
 * fetch, never fall back to a locally-chosen id.
 */
export function extractGatewayRequestId(headers: Record<string, string | undefined>): string | undefined {
    const id = headers[GATEWAY_REQUEST_ID_HEADER]
    return id && GATEWAY_REQUEST_ID_PATTERN.test(id) ? id : undefined
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
 * Parse a settled-usage response into a provenance-tagged cost; `null` if
 * absent/blank/non-numeric/negative. Blank matters because `Number('') === 0`
 * would settle as a real $0; negatives aren't settlements we model.
 */
export function gatewaySettledCost(usage: Pick<GatewayUsage, 'cost_usd'>): GatewaySettledCost | null {
    if (typeof usage.cost_usd === 'string' && usage.cost_usd.trim() === '') {
        return null
    }
    const usd = Number(usage.cost_usd)
    return Number.isFinite(usd) && usd >= 0 ? { source: 'gateway', usd } : null
}

/**
 * The single point deciding whether a cost may reach analytics. Throws on
 * anything not `source: 'gateway'` with finite non-negative `usd` — including a
 * cast-in object — so the pi-estimate leak can't return. Sinks catch around it.
 */
export function assertGatewayProvenance(cost: { source?: unknown; usd?: unknown }): GatewaySettledCost {
    if (cost.source !== 'gateway' || typeof cost.usd !== 'number' || !Number.isFinite(cost.usd) || cost.usd < 0) {
        throw new Error(`gateway-wire: refusing non-gateway cost provenance (source=${String(cost.source)})`)
    }
    return { source: 'gateway', usd: cost.usd }
}
