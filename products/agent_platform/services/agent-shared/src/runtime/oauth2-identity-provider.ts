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

export class Oauth2AuthProvider implements IdentityProvider {
    // Typed `boolean` (not the literal `false`) so an identity-establishing
    // subclass can override it to `true`.
    readonly establishesIdentity: boolean = false

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
        const token = await this.tokenRequest({
            grant_type: 'authorization_code',
            code,
            redirect_uri: state.redirectUri,
            code_verifier: state.codeVerifier,
        })
        const subject = await this.deriveSubject(token.access_token)
        await this.deps.credentials.put({
            teamId: state.teamId,
            applicationId: state.applicationId,
            agentUserId: state.agentUserId,
            provider: this.id,
            credential: this.toStored(token),
            scopes: token.scope ? token.scope.split(' ') : state.scopes,
            subject,
        })
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
