/**
 * Generic OAuth2 (auth-code + PKCE) identity provider. One implementation
 * serves every bring-your-own provider (GitHub, Linear, the `dogs` test IdP) —
 * the differences are all config (endpoints, client id/secret, scopes). Never
 * asserts a PostHog identity (`establishesIdentity = false`).
 */

import { createHash, randomBytes } from 'node:crypto'

import type { Credential } from './credential-broker'
import type { HttpFetcher } from './http-client'
import type { IdentityCredentialStore, LinkedCredential, StoredCredential } from './identity-credential-store'
import type { IdentityLinkStateStore } from './identity-link-state-store'
import type {
    IdentityCompleteInput,
    IdentityCompleteResult,
    IdentityInitiateInput,
    IdentityInitiateResult,
    IdentityProvider,
    IdentityResolveInput,
} from './identity-provider'

export interface Oauth2ProviderConfig {
    id: string
    /** Broker key; defaults to `id`. */
    credentialTarget?: string
    /** Who the credential acts as. Default `principal`. See `IdentityProvider.binding`. */
    binding?: 'principal' | 'agent'
    authorizeUrl: string
    tokenUrl: string
    clientId: string
    /** Omit for public PKCE clients. */
    clientSecret?: string
    scopes?: string[]
    userinfoUrl?: string
}

export interface Oauth2ProviderDeps {
    config: Oauth2ProviderConfig
    links: IdentityLinkStateStore
    credentials: IdentityCredentialStore
    http: HttpFetcher
    /** Refresh this far before expiry. Default 60s. */
    refreshSkewMs?: number
    now?: () => number
}

interface TokenResponse {
    access_token: string
    refresh_token?: string
    token_type?: string
    expires_in?: number
    scope?: string
}

const b64url = (buf: Buffer): string => buf.toString('base64url')

/** Set-equal comparison of two host lists (order/dupes-insensitive). */
const hostsMatch = (a: string[], b: string[]): boolean => {
    const bs = new Set(b)
    return a.length === bs.size && a.every((h) => bs.has(h))
}

/** Whether a token-endpoint error body is an OAuth `invalid_grant` (dead/rotated
 *  refresh token, app de-authorized). */
const isInvalidGrant = (body: string): boolean => {
    try {
        return (JSON.parse(body) as { error?: string }).error === 'invalid_grant'
    } catch {
        return false
    }
}

/**
 * The IdP rejected our refresh token as `invalid_grant` (revoked at the IdP, app
 * removed, single-use token already rotated). Distinct from transient 5xx/network
 * so the caller can flip the credential out of `active` instead of retrying — for
 * an agent-scoped row that retry would fan out across every asker.
 */
export class OauthInvalidGrantError extends Error {
    constructor(readonly provider: string) {
        super(`oauth_invalid_grant: ${provider}`)
        this.name = 'OauthInvalidGrantError'
    }
}

export class Oauth2AuthProvider implements IdentityProvider {
    // Typed `boolean` (not the literal `false`) so an identity-establishing
    // subclass can override it to `true`.
    readonly establishesIdentity: boolean = false

    // Per-pod single-flight gate for token refresh, keyed by the row a refresh
    // would write. For `binding: 'agent'` every asker shares one row, so without
    // this N concurrent sessions would all fire `refresh_token` at the skew
    // window — single-use rotated tokens break and IdP rate limits trip. One
    // in-flight refresh per key; the rest await its result.
    private readonly inflightRefresh = new Map<string, Promise<StoredCredential>>()

    // `protected` (not `private`) so an identity-establishing subclass
    // (PostHogAuthProvider) can reach the config + http to derive a subject.
    constructor(protected readonly deps: Oauth2ProviderDeps) {}

    get id(): string {
        return this.deps.config.id
    }

    get credentialTarget(): string {
        return this.deps.config.credentialTarget ?? this.deps.config.id
    }

    get binding(): 'principal' | 'agent' {
        return this.deps.config.binding ?? 'principal'
    }

    allowedHosts(): string[] {
        const hosts = new Set<string>()
        for (const u of [this.deps.config.authorizeUrl, this.deps.config.tokenUrl, this.deps.config.userinfoUrl]) {
            if (u) {
                hosts.add(new URL(u).host)
            }
        }
        return [...hosts]
    }

    async initiate(input: IdentityInitiateInput): Promise<IdentityInitiateResult> {
        const verifier = b64url(randomBytes(32))
        const challenge = b64url(createHash('sha256').update(verifier).digest())
        const scopes = input.scopes.length ? input.scopes : (this.deps.config.scopes ?? [])
        const stateId = await this.deps.links.create({
            teamId: input.teamId,
            applicationId: input.applicationId,
            agentUserId: input.agentUserId,
            provider: this.id,
            scopes,
            codeVerifier: verifier,
            redirectUri: input.redirectUri,
        })
        const u = new URL(this.deps.config.authorizeUrl)
        u.searchParams.set('response_type', 'code')
        u.searchParams.set('client_id', this.deps.config.clientId)
        u.searchParams.set('redirect_uri', input.redirectUri)
        if (scopes.length) {
            u.searchParams.set('scope', scopes.join(' '))
        }
        u.searchParams.set('state', stateId)
        u.searchParams.set('code_challenge', challenge)
        u.searchParams.set('code_challenge_method', 'S256')
        return { authorizeUrl: u.toString(), stateId }
    }

    async complete(input: IdentityCompleteInput): Promise<IdentityCompleteResult> {
        if (input.query.error) {
            throw new Error(`oauth_error: ${input.query.error}`)
        }
        const code = input.query.code
        if (!code) {
            throw new Error('oauth_missing_code')
        }
        // Single-use consume binds (state → agent_user, provider, verifier).
        const state = await this.deps.links.consume(input.stateId)
        if (!state || state.provider !== this.id) {
            throw new Error('oauth_invalid_state')
        }
        // Validate the binding ↔ principal invariant BEFORE spending the auth code.
        // An `agent` link is owner-initiated and carries no principal; a `principal`
        // link must carry one. A mismatch means the provider's binding was flipped
        // between initiate and complete — reject rather than store the token under
        // the wrong scope (an agent row built from a per-asker link would silently
        // make every asker act as that user, bypassing acknowledge_shared_credential).
        if (this.binding === 'agent') {
            if (state.agentUserId !== null) {
                throw new Error('oauth_link_binding_mismatch')
            }
        } else if (!state.agentUserId) {
            throw new Error('oauth_link_missing_principal')
        }
        const token = await this.tokenRequest({
            grant_type: 'authorization_code',
            code,
            redirect_uri: state.redirectUri,
            code_verifier: state.codeVerifier,
        })
        const subject = await this.deriveSubject(token.access_token)
        const scopes = token.scope ? token.scope.split(' ') : state.scopes
        // Pin the endpoint hosts this credential is being connected under, so a
        // later same-id revision can't repoint them to exfiltrate the bearer.
        const credential: StoredCredential = { ...this.toStored(token), bound_hosts: this.allowedHosts() }
        if (this.binding === 'agent') {
            // Agent-scoped (owner-initiated) link: one shared credential, app-scoped.
            await this.deps.credentials.putAgentScoped({
                teamId: state.teamId,
                applicationId: state.applicationId,
                provider: this.id,
                credential,
                scopes,
                subject,
            })
        } else {
            await this.deps.credentials.put({
                teamId: state.teamId,
                applicationId: state.applicationId,
                // Non-null here — the principal guard above already rejected null.
                agentUserId: state.agentUserId as string,
                provider: this.id,
                credential,
                scopes,
                subject,
            })
        }
        return { agentUserId: state.agentUserId, provider: this.id }
    }

    /**
     * The external subject this link proves, if any. Base provider establishes
     * no identity → undefined. An identity-establishing subclass overrides this
     * (e.g. PostHog reads /oauth/userinfo `sub`) so `complete()` stamps it on
     * the stored credential. Runs once, at link time, with a fresh access token.
     */
    protected async deriveSubject(_accessToken: string): Promise<string | undefined> {
        return undefined
    }

    async resolve(input: IdentityResolveInput): Promise<Credential | null> {
        // `agent` binding resolves one app-scoped credential shared by every
        // asker (keyed by application, not principal); `principal` resolves the
        // asker's own linked credential.
        const isAgent = this.binding === 'agent'
        if (!isAgent && !input.agentUserId) {
            // A principal credential is keyed by the asker; the gate normally
            // guarantees one before calling, but guard so a null/empty asker can
            // never silently key the wrong row.
            return null
        }
        const linked = isAgent
            ? await this.deps.credentials.getAgentScoped(input.applicationId, this.id)
            : await this.deps.credentials.get(input.agentUserId as string, this.id)
        if (!linked) {
            return null
        }
        let stored = linked.credential
        // Host-rebinding guard: refuse a credential whose connect-time endpoint
        // hosts no longer match the live provider config. An editor can keep a
        // provider id but repoint token/userinfo at a host they control on a new
        // revision; without this the stored bearer would be sent there. Legacy
        // credentials (no recorded bound_hosts) skip the check.
        if (stored.bound_hosts && !hostsMatch(stored.bound_hosts, this.allowedHosts())) {
            throw new Error('oauth_provider_host_rebound')
        }
        const now = (this.deps.now ?? Date.now)()
        const skew = this.deps.refreshSkewMs ?? 60_000
        if (stored.expires_at && stored.expires_at - skew <= now && stored.refresh_token) {
            try {
                stored = await this.refreshSingleFlight(input, linked, stored.refresh_token)
            } catch (err) {
                if (err instanceof OauthInvalidGrantError) {
                    // Dead refresh token: flip the row out of `active` so subsequent
                    // resolves short-circuit to "not connected" instead of every
                    // asker re-hammering the IdP with the same doomed refresh.
                    if (isAgent) {
                        await this.deps.credentials.revokeAgentScoped(input.applicationId, this.id)
                    } else {
                        await this.deps.credentials.revoke(input.agentUserId as string, this.id)
                    }
                    return null
                }
                throw err
            }
        }
        return {
            kind: 'oauth_bearer',
            token: stored.access_token,
            provider: this.id,
            scopes: linked.scopes,
            expires_at: stored.expires_at,
        }
    }

    /**
     * Refresh the access token, persisting it back to the same row shape it came
     * from, under a per-key single-flight gate. Concurrent resolves for the same
     * credential row share one IdP refresh + one write rather than racing.
     */
    private async refreshSingleFlight(
        input: IdentityResolveInput,
        linked: LinkedCredential,
        refreshToken: string
    ): Promise<StoredCredential> {
        const isAgent = this.binding === 'agent'
        const key = isAgent ? `agent:${input.applicationId}:${this.id}` : `principal:${input.agentUserId}:${this.id}`
        const existing = this.inflightRefresh.get(key)
        if (existing) {
            return existing
        }
        const p = (async (): Promise<StoredCredential> => {
            const token = await this.tokenRequest({ grant_type: 'refresh_token', refresh_token: refreshToken })
            const refreshed = this.toStored(token, refreshToken)
            // Preserve the connect-time host pin across refreshes (toStored omits it).
            refreshed.bound_hosts = linked.credential.bound_hosts
            if (isAgent) {
                await this.deps.credentials.putAgentScoped({
                    teamId: input.teamId,
                    applicationId: input.applicationId,
                    provider: this.id,
                    credential: refreshed,
                    scopes: linked.scopes,
                })
            } else {
                await this.deps.credentials.put({
                    teamId: input.teamId,
                    applicationId: input.applicationId,
                    agentUserId: input.agentUserId as string,
                    provider: this.id,
                    credential: refreshed,
                    scopes: linked.scopes,
                })
            }
            return refreshed
        })()
        this.inflightRefresh.set(key, p)
        try {
            return await p
        } finally {
            this.inflightRefresh.delete(key)
        }
    }

    private toStored(t: TokenResponse, fallbackRefresh?: string): StoredCredential {
        const now = (this.deps.now ?? Date.now)()
        return {
            access_token: t.access_token,
            refresh_token: t.refresh_token ?? fallbackRefresh,
            token_type: t.token_type,
            expires_at: t.expires_in ? now + t.expires_in * 1000 : undefined,
        }
    }

    private async tokenRequest(params: Record<string, string>): Promise<TokenResponse> {
        const body = new URLSearchParams({ ...params, client_id: this.deps.config.clientId })
        if (this.deps.config.clientSecret) {
            body.set('client_secret', this.deps.config.clientSecret)
        }
        const res = await this.deps.http.fetch(this.deps.config.tokenUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
            body: body.toString(),
        })
        if (!res.ok) {
            const text = await res.text().catch(() => '')
            // A failed refresh with `invalid_grant` is terminal (token dead at the
            // IdP), not transient — surface it typed so resolve() can stop retrying.
            if (params.grant_type === 'refresh_token' && isInvalidGrant(text)) {
                throw new OauthInvalidGrantError(this.id)
            }
            throw new Error(`oauth_token_http_${res.status}: ${text.slice(0, 200)}`)
        }
        const json = (await res.json()) as TokenResponse
        if (!json.access_token) {
            throw new Error('oauth_token_no_access_token')
        }
        return json
    }
}
