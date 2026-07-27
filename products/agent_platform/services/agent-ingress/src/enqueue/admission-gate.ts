/**
 * Edge admission wiring. Builds an `AdmissionService` for a revision from the
 * ingress's identity stores + the revision's declared providers/env. Returns
 * null only when the agent declares no authoritative provider (passthrough).
 * The stores are required — the ingress always wires them — so a null return is
 * unambiguously "passthrough", never "misconfigured" (which previously fell
 * open). Shared by the Slack trigger, the chat trigger (resolve), and the
 * `/link/:provider/callback` route (complete).
 */

import {
    AdmissionService,
    buildIdentityRegistry,
    buildLinkCallbackUrl,
    jwtPrincipalSubject,
    type AgentRevision,
    type EncryptedFields,
    type HttpFetcher,
    type IdentityCredentialStore,
    type IdentityLinkStateStore,
    type IdentityStore,
    type IngressRoutingMode,
    type SessionPrincipal,
    type TransportBindingStore,
    type TransportClaim,
} from '@posthog/agent-shared'

export interface AdmissionDepsBundle {
    identities: IdentityStore
    identityLinks: IdentityLinkStateStore
    identityCredentials: IdentityCredentialStore
    transportBindings: TransportBindingStore
    envEncryption: EncryptedFields
    http: HttpFetcher
    posthogApiBaseUrl?: string
    /** Ingress routing mode; builds the OAuth callback host (`domain` → per-agent, `path` → flat). */
    routingMode?: IngressRoutingMode
    /** Domain suffix for domain mode (e.g. `.agents.us.posthog.com`). */
    domainSuffix?: string
    /** Flat ingress base URL for the OAuth callback in `path` mode (dev). */
    publicBaseUrl?: string
}

/**
 * Build the transport claim for an authenticated HTTP (chat) principal.
 *
 * Only user-shaped principals (posthog, jwt) carry a stable per-sender subject
 * admission can bind a canonical identity to. Machine principals
 * (shared_secret, posthog_internal, service) and the public opt-in anonymous
 * principal have no human behind the transport to resolve — returning null
 * makes the chat trigger FAIL CLOSED (403, nothing enqueued): an authoritative
 * provider means "verified human identity required", and a coexisting
 * public/shared-secret/internal auth mode must not silently void that gate.
 * (Minting a claim instead would be worse — a claim keyed on a shared
 * principal would let one secret holder bind an identity every other holder
 * is then admitted as.)
 *
 * `transport` deliberately equals the principal kind (`posthog` / `jwt`), so
 * the transport AgentUser admission creates is the SAME row
 * `agentUserIdForPrincipal` maps the principal to — bindings and per-asker
 * secondary credentials hang off one AgentUser, not two parallel ones.
 *
 * The request bearer rides on the claim ONLY when it is a credential FOR the
 * authoritative provider (a PostHog bearer on a `kind: posthog` provider).
 * Attaching an unrelated token (a JWT, or a PostHog bearer under an oauth2
 * authoritative provider) would trip admission's freshness rule — a
 * present-but-invalid bearer forces re-auth without ever consulting the
 * durable binding, locking out users who already linked.
 */
export function httpTransportClaim(
    principal: SessionPrincipal,
    bearer: string | null,
    revision: AgentRevision
): TransportClaim | null {
    switch (principal.kind) {
        case 'posthog': {
            const authoritative = revision.spec.identity_providers.find(
                (p) => p.id === revision.spec.authoritative_provider
            )
            const bearerIsProviderCredential = authoritative?.kind === 'posthog'
            // `subjectId` (the PostHog user UUID) must equal the subject the
            // provider's userinfo proves for this bearer — the transport row
            // keys on the former, the canonical row on the latter, and
            // admission assumes they name the same person for `kind: posthog`.
            return {
                transport: 'posthog',
                subjectId: principal.user_id,
                ...(bearer && bearerIsProviderCredential ? { bearer: { token: bearer } } : {}),
                ...(principal.email ? { attributes: { email: principal.email } } : {}),
            }
        }
        case 'jwt':
            // Issuer-scoped (see `jwtPrincipalSubject`): colliding `sub`s across
            // two configured jwt modes must not resolve each other's binding.
            // The JWT proves the transport claim, not the authoritative identity —
            // it is never attached as a bearer.
            return { transport: 'jwt', subjectId: jwtPrincipalSubject(principal) }
        default:
            return null
    }
}

/** Build an `AdmissionService` for a revision, or null when the agent declares
 *  no authoritative provider (passthrough). `slug` is the agent's slug — in
 *  domain mode the OAuth callback lands on that agent's own host. */
export function buildAdmission(
    deps: AdmissionDepsBundle,
    revision: AgentRevision,
    slug: string
): AdmissionService | null {
    if (!revision.spec.authoritative_provider) {
        return null
    }
    const env = deps.envEncryption.decryptJsonEnv(revision.encrypted_env)
    const registry = buildIdentityRegistry(revision.spec.identity_providers, {
        links: deps.identityLinks,
        credentials: deps.identityCredentials,
        http: deps.http,
        secret: (name) => env[name],
        posthogBaseUrl: deps.posthogApiBaseUrl,
    })
    return new AdmissionService({
        registry,
        identities: deps.identities,
        bindings: deps.transportBindings,
        credentials: deps.identityCredentials,
        redirectUriFor: (p) => {
            const url = buildLinkCallbackUrl({
                routingMode: deps.routingMode ?? 'path',
                domainSuffix: deps.domainSuffix,
                publicBaseUrl: deps.publicBaseUrl,
                slug,
                provider: p,
            })
            if (!url) {
                throw new Error('link_callback_url_unconfigured')
            }
            return url
        },
    })
}
