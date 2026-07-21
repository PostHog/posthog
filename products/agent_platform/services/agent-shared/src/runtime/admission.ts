/**
 * Admission — the edge gate. Given a `TransportClaim` and an agent revision,
 * resolves a verified canonical identity from the agent's authoritative provider,
 * or returns an auth block to deliver. Runs BEFORE a session is enqueued.
 *
 * Canonical identity = an `AgentUser` keyed on (authoritative provider, subject).
 * The transport principal is a separate `AgentUser` (kind=transport); a durable
 * `TransportBinding` connects them. Secondary providers link to the canonical id.
 */

import type { AgentUser, IdentityStore } from '../persistence/identity-store'
import type { AgentApplication, AgentRevision } from '../spec/spec'
import type { IdentityCredentialStore } from './identity-credential-store'
import { IdentityProviderUnavailableError } from './identity-provider'
import type { BearerVerification, IdentityProviderRegistry } from './identity-provider'
import type { AdmissionResult, TransportClaim, VerifiedIdentity } from './transport'
import type { TransportBindingStore } from './transport-binding-store'

export type AdmissionLog = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void

export interface AdmissionDeps {
    registry: IdentityProviderRegistry
    identities: IdentityStore
    bindings: TransportBindingStore
    credentials: IdentityCredentialStore
    /** Build the OAuth callback URL for a provider. */
    redirectUriFor: (providerId: string) => string
    log?: AdmissionLog
}

/** Canonical identities are AgentUsers namespaced so a provider id can never
 *  collide with a transport id (e.g. an agent named provider 'posthog' vs a
 *  hypothetical 'posthog' transport). */
export function canonicalKind(providerId: string): string {
    return `identity:${providerId}`
}

export class AdmissionService {
    constructor(private readonly deps: AdmissionDeps) {}

    /** Resolve admission for an inbound transport claim against an agent revision. */
    async resolve(
        claim: TransportClaim,
        ctx: { application: AgentApplication; revision: AgentRevision }
    ): Promise<AdmissionResult> {
        const teamId = ctx.application.team_id
        const applicationId = ctx.application.id
        const authoritativeId = ctx.revision.spec.authoritative_provider

        // The transport principal always exists — per-message sender for audit,
        // bindings, and per-asker secondary creds.
        const transportUser = await this.deps.identities.findOrCreate({
            team_id: teamId,
            application_id: applicationId,
            principal_kind: claim.transport,
            principal_id: claim.subjectId,
            metadata: claim.attributes,
        })

        if (!authoritativeId) {
            return { kind: 'passthrough', transportAgentUserId: transportUser.id }
        }

        const provider = this.deps.registry.get(authoritativeId)
        if (!provider) {
            this.deps.log?.('error', 'admission.unknown_provider', { provider: authoritativeId })
            return { kind: 'error', reason: `unknown_authoritative_provider:${authoritativeId}` }
        }

        // 1. Per-request bearer the provider can verify inline (HTTP transports).
        //    A bearer is a PER-REQUEST proof: verify it on every request, BEFORE
        //    consulting any durable binding. A binding must never substitute for
        //    a fresh bearer check — otherwise a revoked or expired token keeps
        //    admitting until the binding is explicitly unbound, silently turning
        //    a one-time link into a permanent grant. So a present-but-invalid
        //    bearer goes straight to re-auth and is NOT rescued by step 2's
        //    binding. (No bearer / no `verifyBearer` → fall to the binding path.)
        if (claim.bearer && provider.verifyBearer) {
            let verified: BearerVerification | null
            try {
                verified = await provider.verifyBearer(claim.bearer.token)
            } catch (err) {
                if (err instanceof IdentityProviderUnavailableError) {
                    // The provider couldn't JUDGE the token (userinfo down /
                    // timed out) — fail closed but retryable. Falling through
                    // to auth_required here would misread an IdP brownout as
                    // mass token revocation.
                    this.deps.log?.('error', 'admission.provider_unavailable', {
                        provider: authoritativeId,
                        detail: err.message,
                    })
                    return { kind: 'error', reason: 'authoritative_provider_unavailable' }
                }
                throw err
            }
            if (verified) {
                // Invariant: a provider that exposes `verifyBearer` is
                // userinfo-backed and can prove a subject, so minting a
                // canonical identity from it is safe — regardless of its
                // `establishesIdentity` flag, which gates link-time secondary-
                // credential stamping, not bearer proof. A future provider
                // with a bearer check that does NOT prove a subject must not
                // define `verifyBearer`.
                const canonical = await this.upsertCanonical(applicationId, teamId, authoritativeId, verified.subject)
                await this.deps.credentials.put({
                    teamId,
                    applicationId,
                    agentUserId: canonical.id,
                    provider: authoritativeId,
                    credential: verified.stored,
                    scopes: verified.scopes,
                    subject: verified.subject,
                })
                await this.deps.bindings.bind({
                    teamId,
                    applicationId,
                    transportAgentUserId: transportUser.id,
                    canonicalAgentUserId: canonical.id,
                    provider: authoritativeId,
                })
                return this.admitted(authoritativeId, canonical, transportUser.id, 'bearer')
            }
            this.deps.log?.('warn', 'admission.bearer_invalid', { provider: authoritativeId })
            // Present-but-invalid → fall through to initiate (re-auth). Do NOT
            // consult the durable binding — freshness must win over a prior link.
        } else {
            // 2. Durable binding → already authenticated. Only when there's no
            //    verifiable per-request bearer (Slack/Discord, where the proof of
            //    identity is the prior OAuth link, not a token on this request).
            const binding = await this.deps.bindings.find(applicationId, transportUser.id)
            if (binding) {
                // Bindings are provider-scoped: if the agent's authoritative
                // provider changed since the link, the old binding is stale —
                // fall through to re-auth against the current provider.
                if (binding.provider !== authoritativeId) {
                    this.deps.log?.('warn', 'admission.stale_binding_provider', {
                        binding_id: binding.id,
                        binding_provider: binding.provider,
                        authoritative_provider: authoritativeId,
                    })
                } else {
                    const canonical = await this.deps.identities.getById(binding.canonicalAgentUserId)
                    if (canonical && canonical.principal_kind === canonicalKind(authoritativeId)) {
                        // The binding is only trustworthy while the underlying
                        // authoritative credential is still active. If it was
                        // revoked or removed (`credentials.get` returns null
                        // for both), the durable link is invalidated — fall
                        // through so the user re-links and a fresh credential
                        // is written before we admit again.
                        const credential = await this.deps.credentials.get(canonical.id, authoritativeId)
                        if (credential) {
                            return this.admitted(authoritativeId, canonical, transportUser.id, 'binding')
                        }
                        this.deps.log?.('warn', 'admission.binding_credential_inactive', {
                            binding_id: binding.id,
                            canonical_id: canonical.id,
                            provider: authoritativeId,
                        })
                    } else {
                        // Dangling / mismatched canonical → fall through to re-auth.
                        this.deps.log?.('warn', 'admission.dangling_binding', { binding_id: binding.id })
                    }
                }
            }
        }

        // 3. Not authenticated → initiate a link bound to the transport principal.
        try {
            const { authorizeUrl } = await provider.initiate({
                agentUserId: transportUser.id,
                teamId,
                applicationId,
                scopes: [], // authoritative scopes come from the provider's own config
                redirectUri: this.deps.redirectUriFor(authoritativeId),
            })
            this.deps.log?.('info', 'admission.auth_required', {
                provider: authoritativeId,
                transport: claim.transport,
            })
            return { kind: 'auth_required', provider: authoritativeId, authorizeUrl }
        } catch (err) {
            this.deps.log?.('error', 'admission.initiate_failed', {
                provider: authoritativeId,
                reason: (err as Error).message,
            })
            return { kind: 'error', reason: (err as Error).message }
        }
    }

    /**
     * Complete an admission OAuth callback: exchange the code, derive the subject,
     * upsert the canonical identity, persist the authoritative credential under it,
     * and write the transport binding. The callback route peeks the link-state to
     * find `providerId`, rebuilds the registry, then calls this.
     */
    async complete(
        providerId: string,
        stateId: string,
        query: Record<string, string | undefined>
    ): Promise<VerifiedIdentity> {
        const provider = this.deps.registry.require(providerId)
        const { state, stored, subject, scopes } = await provider.exchange({ stateId, query })
        if (!subject) {
            // The authoritative provider MUST prove a subject (userinfo). Fail closed.
            throw new Error('admission_no_subject')
        }
        const transportAgentUserId = state.agentUserId
        const canonical = await this.upsertCanonical(state.applicationId, state.teamId, providerId, subject)
        await this.deps.credentials.put({
            teamId: state.teamId,
            applicationId: state.applicationId,
            agentUserId: canonical.id,
            provider: providerId,
            credential: stored,
            scopes,
            subject,
        })
        await this.deps.bindings.bind({
            teamId: state.teamId,
            applicationId: state.applicationId,
            transportAgentUserId,
            canonicalAgentUserId: canonical.id,
            provider: providerId,
        })
        this.deps.log?.('info', 'admission.linked', { provider: providerId, canonical_id: canonical.id })
        return { provider: providerId, subject, canonicalId: canonical.id, transportAgentUserId }
    }

    private async upsertCanonical(
        applicationId: string,
        teamId: number,
        providerId: string,
        subject: string
    ): Promise<AgentUser> {
        return this.deps.identities.findOrCreate({
            team_id: teamId,
            application_id: applicationId,
            principal_kind: canonicalKind(providerId),
            principal_id: subject,
        })
    }

    private admitted(
        provider: string,
        canonical: AgentUser,
        transportAgentUserId: string,
        source: string
    ): AdmissionResult {
        this.deps.log?.('info', 'admission.admitted', { provider, source, canonical_id: canonical.id })
        return {
            kind: 'admitted',
            identity: {
                provider,
                subject: canonical.principal_id,
                canonicalId: canonical.id,
                transportAgentUserId,
            },
        }
    }
}
