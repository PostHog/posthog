/**
 * Edge admission wiring. Builds an `AdmissionService` for a revision from the
 * ingress's identity stores + the revision's declared providers/env. Returns
 * null only when the agent declares no authoritative provider (passthrough).
 * The stores are required — the ingress always wires them — so a null return is
 * unambiguously "passthrough", never "misconfigured" (which previously fell
 * open). Shared by the Slack trigger (resolve) and the
 * `/link/:provider/callback` route (complete).
 */

import {
    AdmissionService,
    buildIdentityRegistry,
    buildLinkCallbackUrl,
    type AgentRevision,
    type EncryptedFields,
    type HttpFetcher,
    type IdentityCredentialStore,
    type IdentityLinkStateStore,
    type IdentityStore,
    type IngressRoutingMode,
    type TransportBindingStore,
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
