/**
 * The ingress OAuth link-callback URL for an agent + provider, matching what the
 * deployed ingress actually serves in each routing mode.
 *
 * MIRROR: `agent_link_callback_url` in
 * products/agent_platform/backend/logic/posthog_identity_app.py. The two MUST
 * produce byte-identical strings — Django registers this as the
 * OAuthApplication `redirect_uri` at promote, the runner sends the same value at
 * authorize time, and the IdP rejects the exchange on any mismatch.
 *
 *   domain → `https://<slug><domainSuffix>/link/<provider>/callback`  (slug in host)
 *   path   → `<publicBaseUrl>/link/<provider>/callback`               (dev: single ingress host)
 *
 * The callback route is registered at the ROOT of the ingress app in both modes
 * (`agent-ingress/src/routing/server.ts` — it recovers the agent from the OAuth
 * `state`, not the host), so the only per-mode difference is how the base host
 * is built: domain mode addresses the agent's own `<slug>` host; path mode (dev)
 * has a single flat ingress host with no slug in the URL.
 *
 * Returns null when the active mode's required input is missing (domain mode
 * without a suffix, path mode without a public base URL, or an empty slug) —
 * the caller then has no reachable callback to offer and should fail the link
 * rather than send the IdP a wrong host.
 */
export type IngressRoutingMode = 'domain' | 'path'

export function buildLinkCallbackUrl(opts: {
    routingMode: IngressRoutingMode
    domainSuffix?: string
    publicBaseUrl?: string
    slug: string
    provider: string
}): string | null {
    const { routingMode, domainSuffix, publicBaseUrl, slug, provider } = opts
    if (!slug) {
        return null
    }
    if (routingMode === 'domain') {
        const suffix = domainSuffix?.trim()
        return suffix ? `https://${slug}${suffix}/link/${provider}/callback` : null
    }
    const base = (publicBaseUrl ?? '').replace(/\/+$/, '')
    return base ? `${base}/link/${provider}/callback` : null
}
