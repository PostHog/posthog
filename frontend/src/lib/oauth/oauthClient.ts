// Token store + refresh for the standalone OAuth frontend. Plain TS (no kea) so that
// `api.ts` and other non-React callers can read a valid bearer token directly.
// `oauthLogic` wraps this for the login UI.

import { OrganizationType, Region, TeamType, UserType } from '~/types'

import { generateCodeChallenge } from './pkce'

export interface OAuthRegionConfig {
    key: Region.US | Region.EU
    label: string
    flag: string
    host: string
    clientId: string
}

// Registered public PKCE client IDs per cloud region (no OAuth for local/self-hosted).
export const OAUTH_REGIONS: Record<Region.US | Region.EU, OAuthRegionConfig> = {
    [Region.US]: {
        key: Region.US,
        label: 'US Cloud',
        flag: '🇺🇸',
        host: 'https://us.posthog.com',
        clientId: '47rGkjTTMRvkbfU1sdSXsqOGLyJBlbMneRkFKhmO',
    },
    [Region.EU]: {
        key: Region.EU,
        label: 'EU Cloud',
        flag: '🇪🇺',
        host: 'https://eu.posthog.com',
        clientId: 'VCRpJggenuNKqALWy2Um35S4mHbUcIPPg5hiA03K',
    },
}

/** The region whose API host matches the given backend host, or null if none. */
export function getRegionForHost(host: string): Region.US | Region.EU | null {
    return Object.values(OAUTH_REGIONS).find((region) => region.host === host)?.key ?? null
}

/** Where the OAuth provider redirects back to — this frontend's own origin (e.g. http://localhost:8010). */
function getRedirectUri(): string {
    return `${window.location.origin}/oauth/callback`
}

const SESSION_KEY = 'ph_oauth_session'
// Tokenless dev marker so the DEBUG-gated backend serves the SPA in OAuth mode (value = region).
// NOT a secure cookie (client-set, forgeable, no httpOnly/Secure) — never gate production auth on
// it. The backend only honors it under DEBUG (see login_required in posthog/views.py).
const OAUTH_MODE_COOKIE = 'ph_oauth_mode'

export interface OAuthSession {
    backendHost: string
    clientId: string
    accessToken: string
    refreshToken: string
    /** Epoch ms when the access token expires. */
    expiresAt: number
}

export interface PendingAuth {
    backendHost: string
    clientId: string
    codeVerifier: string
    state: string
    /** In-app path to return to once the flow completes. */
    returnTo: string
}

interface TokenResponse {
    access_token: string
    refresh_token: string
    expires_in: number
}

/**
 * OAuth mode is active when a cloud OAuth session is stored: the frontend then talks to the
 * remote region with a bearer token instead of the local backend's session cookie.
 */
export function isOAuthMode(): boolean {
    return !!getStoredSession()
}

export function getStoredSession(): OAuthSession | null {
    try {
        const raw = window.localStorage.getItem(SESSION_KEY)
        return raw ? (JSON.parse(raw) as OAuthSession) : null
    } catch {
        return null
    }
}

export function getBackendHost(): string | null {
    return getStoredSession()?.backendHost ?? null
}

function storeSession(session: OAuthSession): void {
    window.localStorage.setItem(SESSION_KEY, JSON.stringify(session))
    // Persistent (400d cap) to track the localStorage session across browser restarts.
    document.cookie = `${OAUTH_MODE_COOKIE}=${getRegionForHost(session.backendHost) ?? '1'}; path=/; Max-Age=34560000; SameSite=Lax`
}

export function clearSession(): void {
    window.localStorage.removeItem(SESSION_KEY)
    document.cookie = `${OAUTH_MODE_COOKIE}=; path=/; Max-Age=0; SameSite=Lax`
    // Drop the bootstrap ids with the session so a later login in the same tab can't read the
    // previous account's ids before its own /api/users/@me/ resolves.
    oauthContextIds = null
}

export interface OAuthContextIds {
    teamId?: TeamType['id']
    organizationId?: OrganizationType['id']
    userId?: UserType['uuid']
}

// In OAuth mode getAppContext() has no server-rendered context, so these bootstrap ids are pushed
// here from userLogic once the remote user loads, and read back by getAppContext's synchronous
// getters. Lives alongside the session (not in getAppContext) so clearSession() can reset it, and
// so getAppContext stays a leaf module — importing the heavy lib/api there caused a module-init cycle.
let oauthContextIds: OAuthContextIds | null = null

export function setOAuthContextIds(ids: OAuthContextIds | null): void {
    oauthContextIds = ids
}

export function getOAuthContextIds(): OAuthContextIds | null {
    return oauthContextIds
}

function sessionFromTokenResponse(backendHost: string, clientId: string, data: TokenResponse): OAuthSession {
    return {
        backendHost,
        clientId,
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresAt: Date.now() + data.expires_in * 1000,
    }
}

/** Full authorize URL for a flow; also computes the S256 challenge from the stored verifier. */
export async function buildAuthorizeUrl(pending: PendingAuth): Promise<string> {
    const codeChallenge = await generateCodeChallenge(pending.codeVerifier)
    const url = new URL(`${pending.backendHost}/oauth/authorize`)
    url.searchParams.set('client_id', pending.clientId)
    url.searchParams.set('redirect_uri', getRedirectUri())
    url.searchParams.set('response_type', 'code')
    url.searchParams.set('code_challenge', codeChallenge)
    url.searchParams.set('code_challenge_method', 'S256')
    url.searchParams.set('scope', '*') // All scopes, just like the desktop app
    url.searchParams.set('state', pending.state)
    return url.toString()
}

/** Exchange the authorization code for tokens and persist the session. */
export async function exchangeCodeForToken(pending: PendingAuth, code: string, state: string): Promise<OAuthSession> {
    if (pending.state !== state) {
        throw new Error('OAuth state mismatch. Please start the login again.')
    }
    // Trailing slash is required: CORS_URLS_REGEX only grants CORS headers to `/oauth/token/`.
    const response = await fetch(`${pending.backendHost}/oauth/token/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            grant_type: 'authorization_code',
            code,
            redirect_uri: getRedirectUri(),
            client_id: pending.clientId,
            code_verifier: pending.codeVerifier,
        }),
    })
    if (!response.ok) {
        throw new Error(`Token exchange failed: ${response.status} ${await response.text()}`)
    }
    const session = sessionFromTokenResponse(
        pending.backendHost,
        pending.clientId,
        (await response.json()) as TokenResponse
    )
    storeSession(session)
    return session
}

// Dedupe concurrent refreshes so a burst of 401s triggers a single token request.
let refreshPromise: Promise<string | null> | null = null

export function refreshAccessToken(): Promise<string | null> {
    if (!refreshPromise) {
        refreshPromise = doRefresh().finally(() => {
            refreshPromise = null
        })
    }
    return refreshPromise
}

async function doRefresh(): Promise<string | null> {
    const session = getStoredSession()
    if (!session) {
        return null
    }
    let response: Response
    try {
        response = await fetch(`${session.backendHost}/oauth/token/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                grant_type: 'refresh_token',
                refresh_token: session.refreshToken,
                client_id: session.clientId,
            }),
        })
    } catch {
        // Network error — keep the session so a later request can retry.
        return null
    }
    if (!response.ok) {
        // A rejected refresh token is terminal: clear the session and force re-login.
        if (response.status === 400 || response.status === 401) {
            clearSession()
        }
        return null
    }
    const updated = sessionFromTokenResponse(
        session.backendHost,
        session.clientId,
        (await response.json()) as TokenResponse
    )
    storeSession(updated)
    return updated.accessToken
}
