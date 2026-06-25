/**
 * Edge admission wiring. Builds an `AdmissionService` for a revision from the
 * ingress's identity stores + the revision's declared providers/env. Returns
 * null when admission isn't configured (missing stores) or the agent declares
 * no authoritative provider (passthrough). Shared by the Slack trigger (resolve)
 * and the `/link/:provider/callback` route (complete).
 */

import {
    AdmissionService,
    buildIdentityRegistry,
    type AgentRevision,
    type EncryptedFields,
    type HttpFetcher,
    type IdentityCredentialStore,
    type IdentityLinkStateStore,
    type IdentityStore,
    type TransportBindingStore,
} from '@posthog/agent-shared'

export interface AdmissionDepsBundle {
    identities?: IdentityStore
    identityLinks?: IdentityLinkStateStore
    identityCredentials?: IdentityCredentialStore
    transportBindings?: TransportBindingStore
    envEncryption?: EncryptedFields
    http?: HttpFetcher
    posthogApiBaseUrl?: string
    publicBaseUrl?: string
}

/** The ingress's own OAuth callback URL for a provider. */
export function admissionRedirectUri(publicBaseUrl: string | undefined, providerId: string): string {
    const base = (publicBaseUrl ?? 'https://agents.posthog.com').replace(/\/+$/, '')
    return `${base}/link/${providerId}/callback`
}

/** Build an `AdmissionService` for a revision, or null if admission isn't wired
 *  or the agent has no authoritative provider. */
export function buildAdmission(deps: AdmissionDepsBundle, revision: AgentRevision): AdmissionService | null {
    const { identities, identityLinks, identityCredentials, transportBindings, envEncryption, http } = deps
    if (!identities || !identityLinks || !identityCredentials || !transportBindings || !envEncryption || !http) {
        return null
    }
    if (!revision.spec.authoritative_provider) {
        return null
    }
    const env = envEncryption.decryptJsonEnv(revision.encrypted_env)
    const registry = buildIdentityRegistry(revision.spec.identity_providers, {
        links: identityLinks,
        credentials: identityCredentials,
        http,
        secret: (name) => env[name],
        posthogBaseUrl: deps.posthogApiBaseUrl,
    })
    return new AdmissionService({
        registry,
        identities,
        bindings: transportBindings,
        credentials: identityCredentials,
        redirectUriFor: (p) => admissionRedirectUri(deps.publicBaseUrl, p),
    })
}
