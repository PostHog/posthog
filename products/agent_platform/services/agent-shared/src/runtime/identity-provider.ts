/**
 * `IdentityProvider` — the pluggable credential axis (Axis B in the plan). One
 * provider owns one external IdP: PostHog (managed), GitHub/Linear/the `dogs`
 * test IdP (generic oauth2). Distinct from the ingress's `AuthProvider`, which
 * bundles the principal-source verifiers (Axis A).
 *
 * All methods key off a generic `agentUserId` — no Slack/PostHog assumptions.
 * `establishesIdentity` is true ONLY for a provider that also proves who the
 * linker is (stamps `subject` on the stored credential — e.g. the PostHog user
 * uuid); capability-only providers leave it false and stamp no subject.
 */

import type { Credential } from './credential-broker'
import type { StoredCredential } from './identity-credential-store'
import type { LinkState } from './identity-link-state-store'

export interface IdentityInitiateInput {
    /** The principal being linked, resolved to an AgentUser id. */
    agentUserId: string
    teamId: number
    applicationId: string
    /** Union of scopes the gated tools/MCPs need from this provider. */
    scopes: string[]
    /** Our callback URL the provider redirects back to. */
    redirectUri: string
}

export interface IdentityInitiateResult {
    authorizeUrl: string
    /** OAuth `state` value — also the single-use link-state row id. */
    stateId: string
}

export interface IdentityCompleteInput {
    stateId: string
    /** Raw callback query (`code`, `state`, `error`, …). */
    query: Record<string, string | undefined>
}

export interface IdentityCompleteResult {
    agentUserId: string
    provider: string
}

export interface IdentityResolveInput {
    agentUserId: string
    teamId: number
    applicationId: string
    scopes: string[]
}

/**
 * Result of the OAuth code exchange WITHOUT persistence. `complete()` (per-asker
 * linking) persists under `state.agentUserId`; admission persists under the
 * canonical identity it derives from `subject` and writes a transport binding.
 * One code path for the crypto (consume + token + deriveSubject), two persistence
 * policies on top.
 */
export interface IdentityExchangeResult {
    /** The consumed single-use link-state (carries team/app/agentUser/redirect). */
    state: LinkState
    /** The fetched access/refresh token, not yet stored. */
    stored: StoredCredential
    /** The proven external subject, if this provider establishes identity. */
    subject?: string
    /** Effective granted scopes (from the token response, else the requested set). */
    scopes: string[]
}

/** Per-request identity proof carried by a transport (e.g. an HTTP bearer the
 *  authoritative provider can introspect inline). No OAuth round-trip needed. */
export interface BearerVerification {
    subject: string
    stored: StoredCredential
    scopes: string[]
}

/**
 * Thrown by `verifyBearer` when the provider could not JUDGE the token —
 * userinfo unreachable, timed out, or answering 5xx — as opposed to judging it
 * invalid (`null`). Admission maps this to a retryable failure instead of
 * `auth_required`: conflating the two would misread an IdP brownout as mass
 * token revocation, sending every holder of a valid bearer to re-auth while
 * hammering the degraded endpoint.
 */
export class IdentityProviderUnavailableError extends Error {
    constructor(
        readonly provider: string,
        detail: string
    ) {
        super(`identity_provider_unavailable: ${provider}: ${detail}`)
        this.name = 'IdentityProviderUnavailableError'
    }
}

export interface IdentityProvider {
    readonly id: string
    /** Broker key tools/MCPs resolve ('posthog_api', 'github', 'dogs', …). Also
     *  the key `createToolIdentity` consults for a trigger-edge seed credential
     *  before falling to the persistent linked-credential store. */
    readonly credentialTarget: string
    /** True only for a provider that proves the linker's identity (stamps `subject`). */
    readonly establishesIdentity: boolean
    /** `principal` = act as the asking user (per-asker link or trigger-edge seed).
     *  `agent` = one author-linked credential shared by the whole agent — a marked
     *  seam, `resolve()` throws `agent_binding_not_implemented` until it lands. */
    readonly binding: 'principal' | 'agent'
    initiate(input: IdentityInitiateInput): Promise<IdentityInitiateResult>
    /** Exchange the OAuth code but do NOT persist. Used by both `complete()` and
     *  the admission engine, which apply different persistence policies. */
    exchange(input: IdentityCompleteInput): Promise<IdentityExchangeResult>
    complete(input: IdentityCompleteInput): Promise<IdentityCompleteResult>
    /** Usable credential for a linked principal, refreshed if stale; null if unlinked. */
    resolve(input: IdentityResolveInput): Promise<Credential | null>
    /** Hosts the resolved bearer may be sent to (SSRF guard). Empty = none allowed. */
    allowedHosts(): string[]
    /** Optional: verify a per-request bearer the transport already carries (HTTP),
     *  proving identity inline without an OAuth round-trip. Undefined = unsupported. */
    verifyBearer?(token: string): Promise<BearerVerification | null>
}

export interface IdentityProviderRegistry {
    get(id: string): IdentityProvider | undefined
    require(id: string): IdentityProvider
    all(): IdentityProvider[]
}

export class MapIdentityProviderRegistry implements IdentityProviderRegistry {
    private readonly byId = new Map<string, IdentityProvider>()

    constructor(providers: IdentityProvider[] = []) {
        for (const p of providers) {
            this.add(p)
        }
    }

    add(provider: IdentityProvider): void {
        if (this.byId.has(provider.id)) {
            throw new Error(`duplicate identity provider id: ${provider.id}`)
        }
        this.byId.set(provider.id, provider)
    }

    get(id: string): IdentityProvider | undefined {
        return this.byId.get(id)
    }

    require(id: string): IdentityProvider {
        const provider = this.byId.get(id)
        if (!provider) {
            throw new Error(`unknown identity provider: ${id}`)
        }
        return provider
    }

    all(): IdentityProvider[] {
        return [...this.byId.values()]
    }
}
