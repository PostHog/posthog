/**
 * Generic OAuth2 (auth-code + PKCE) identity provider. One implementation
 * serves every bring-your-own provider (GitHub, Linear, the `dogs` test IdP) —
 * the differences are all config (endpoints, client id/secret, scopes). Never
 * asserts a PostHog identity (`establishesIdentity = false`).
 */

import { createHash, randomBytes } from 'node:crypto'

import type { Credential } from './credential-broker'
import type { HttpFetcher } from './http-client'
import type { IdentityCredentialStore, StoredCredential } from './identity-credential-store'
import type { IdentityLinkStateStore } from './identity-link-state-store'
import { IdentityProviderUnavailableError } from './identity-provider'
import type {
    BearerVerification,
    IdentityCompleteInput,
    IdentityCompleteResult,
    IdentityExchangeResult,
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

/** Bearer verification blocks the chat request — far tighter than the 30s fetch default. */
const VERIFY_BEARER_TIMEOUT_MS = 5_000

export class Oauth2AuthProvider implements IdentityProvider {
    // Typed `boolean` (not the literal `false`) so an identity-establishing
    // subclass can override it to `true`.
    readonly establishesIdentity: boolean = false

    /**
     * Per-request bearer verification via userinfo. Assigned in the constructor
     * (not a prototype method) so it is genuinely `undefined` when the provider
     * has no `userinfoUrl` — admission treats a present `verifyBearer` as "this
     * provider can judge bearers", and a present-but-invalid bearer forces
     * re-auth WITHOUT consulting the durable binding. A stub that always
     * returned null would therefore lock bound users out.
     */
    readonly verifyBearer?: (token: string) => Promise<BearerVerification | null>

    // `protected` (not `private`) so an identity-establishing subclass
    // (PostHogAuthProvider) can reach the config + http to derive a subject.
    constructor(protected readonly deps: Oauth2ProviderDeps) {
        if (deps.config.userinfoUrl) {
            const userinfoUrl = deps.config.userinfoUrl
            this.verifyBearer = async (token: string): Promise<BearerVerification | null> => {
                // Runs on the chat hot path (every request), so: a tight
                // timeout instead of the fetcher's 30s default, and only the
                // provider's actual judgement on the token (401/403) reads as
                // "invalid". Transport failures, timeouts, and server errors
                // say nothing about the token — surface them as
                // `IdentityProviderUnavailableError` so admission fails closed
                // but RETRYABLE instead of demanding re-auth.
                let res: Response
                try {
                    res = await this.deps.http.fetch(userinfoUrl, {
                        method: 'GET',
                        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
                        signal: AbortSignal.timeout(VERIFY_BEARER_TIMEOUT_MS),
                    })
                } catch (err) {
                    throw new IdentityProviderUnavailableError(
                        this.id,
                        err instanceof Error ? err.message : 'userinfo_fetch_failed'
                    )
                }
                if (res.status === 401 || res.status === 403) {
                    return null
                }
                if (!res.ok) {
                    throw new IdentityProviderUnavailableError(this.id, `userinfo_status_${res.status}`)
                }
                let json: { sub?: string }
                try {
                    json = (await res.json()) as { sub?: string }
                } catch {
                    throw new IdentityProviderUnavailableError(this.id, 'userinfo_malformed_body')
                }
                const subject = typeof json.sub === 'string' && json.sub.length > 0 ? json.sub : undefined
                if (!subject) {
                    // 200 but no provable subject — the provider can't establish
                    // who this is, which for admission is the same as invalid.
                    return null
                }
                // The bearer is the credential — no refresh token and no known
                // expiry; admission re-verifies it on every request anyway.
                return { subject, stored: { access_token: token }, scopes: [] }
            }
        }
    }

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

    /**
     * Exchange the authorization code for a token and derive the subject, but do
     * NOT persist. Both `complete()` (per-asker linking) and the admission engine
     * build on this — they differ only in WHERE the credential lands.
     */
    async exchange(input: IdentityCompleteInput): Promise<IdentityExchangeResult> {
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
        const token = await this.tokenRequest({
            grant_type: 'authorization_code',
            code,
            redirect_uri: state.redirectUri,
            code_verifier: state.codeVerifier,
        })
        return {
            state,
            stored: this.toStored(token),
            // The discoverable subject (for admission/canonical identity), regardless
            // of `establishesIdentity` — which only gates secondary-credential stamping.
            subject: await this.fetchSubject(token.access_token),
            scopes: token.scope ? token.scope.split(' ') : state.scopes,
        }
    }

    async complete(input: IdentityCompleteInput): Promise<IdentityCompleteResult> {
        const { state, stored, subject, scopes } = await this.exchange(input)
        await this.deps.credentials.put({
            teamId: state.teamId,
            applicationId: state.applicationId,
            agentUserId: state.agentUserId,
            provider: this.id,
            credential: stored,
            scopes,
            // A capability-only link makes no identity claim — stamp a subject only
            // when this provider establishes identity.
            subject: this.establishesIdentity ? subject : undefined,
        })
        return { agentUserId: state.agentUserId, provider: this.id }
    }

    /** Read the provider's stable subject from userinfo, if configured. Best-effort:
     *  a hiccup just yields no subject, never blocks the link. */
    protected async fetchSubject(accessToken: string): Promise<string | undefined> {
        const url = this.deps.config.userinfoUrl
        if (!url) {
            return undefined
        }
        try {
            const res = await this.deps.http.fetch(url, {
                method: 'GET',
                headers: { Authorization: `Bearer ${accessToken}`, Accept: 'application/json' },
            })
            if (!res.ok) {
                return undefined
            }
            const json = (await res.json()) as { sub?: string }
            return typeof json.sub === 'string' && json.sub.length > 0 ? json.sub : undefined
        } catch {
            return undefined
        }
    }

    async resolve(input: IdentityResolveInput): Promise<Credential | null> {
        // `agent` binding resolves one app-scoped credential shared by every
        // asker; `getAgentScoped` is a marked seam that throws until it lands.
        const linked =
            this.binding === 'agent'
                ? await this.deps.credentials.getAgentScoped(input.applicationId, this.id)
                : await this.deps.credentials.get(input.agentUserId, this.id)
        if (!linked) {
            return null
        }
        let stored = linked.credential
        const now = (this.deps.now ?? Date.now)()
        const skew = this.deps.refreshSkewMs ?? 60_000
        if (stored.expires_at && stored.expires_at - skew <= now && stored.refresh_token) {
            const token = await this.tokenRequest({ grant_type: 'refresh_token', refresh_token: stored.refresh_token })
            stored = this.toStored(token, stored.refresh_token)
            await this.deps.credentials.put({
                teamId: input.teamId,
                applicationId: input.applicationId,
                agentUserId: input.agentUserId,
                provider: this.id,
                credential: stored,
                scopes: linked.scopes,
            })
        }
        return {
            kind: 'oauth_bearer',
            token: stored.access_token,
            provider: this.id,
            scopes: linked.scopes,
            expires_at: stored.expires_at,
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
            throw new Error(`oauth_token_http_${res.status}: ${text.slice(0, 200)}`)
        }
        const json = (await res.json()) as TokenResponse
        if (!json.access_token) {
            throw new Error('oauth_token_no_access_token')
        }
        return json
    }
}
