/**
 * Session cookie — sealed token bundle.
 *
 * Stores the OAuth access_token + refresh_token in an HTTP-only,
 * SameSite=Lax, sealed cookie. The cookie value is encrypted +
 * signed via `iron-session` so the browser can't read or tamper with
 * the tokens. Everything related to "who is the user" flows through
 * here; nothing else in the app should touch cookies directly.
 *
 * Server-side only — never imported by browser code.
 */

import { sealData, unsealData } from 'iron-session'
import { cookies } from 'next/headers'

import { getConfig } from '@/lib/config'

function cookieSecret(): string {
    return getConfig().oauthCookieSecret
}

function cookieSecure(): boolean {
    return getConfig().nodeEnv === 'production'
}

const COOKIE_NAME = 'agent-console-session'
const COOKIE_TTL_SECONDS = 60 * 60 * 24 * 7 // 7 days

export interface SessionPayload {
    accessToken: string
    refreshToken: string
    /** Epoch ms when the access_token expires (used to refresh proactively). */
    accessTokenExpiresAt: number
    /** Scopes the user granted — informational; the server is authoritative. */
    scope: string
    /** OIDC `sub` claim, when present — purely informational for the UI. */
    sub?: string
    /**
     * The user's "current team" (project) id, fetched at callback time
     * from `/api/users/@me/`. All `/api/projects/<id>/agent_*` calls
     * scope to this. v0.1: surface a project picker in the UI and let
     * the user switch; this is the initial default.
     */
    teamId?: number
}

export async function getSession(): Promise<SessionPayload | null> {
    const store = await cookies()
    const raw = store.get(COOKIE_NAME)?.value
    if (!raw) {
        return null
    }
    try {
        return await unsealData<SessionPayload>(raw, { password: cookieSecret(), ttl: COOKIE_TTL_SECONDS })
    } catch {
        // Tampered / expired — treat as no session. The login flow will
        // overwrite the cookie cleanly.
        return null
    }
}

export async function setSession(payload: SessionPayload): Promise<void> {
    const sealed = await sealData(payload, { password: cookieSecret(), ttl: COOKIE_TTL_SECONDS })
    const store = await cookies()
    store.set(COOKIE_NAME, sealed, {
        httpOnly: true,
        sameSite: 'lax',
        secure: cookieSecure(),
        path: '/',
        maxAge: COOKIE_TTL_SECONDS,
    })
}

export async function clearSession(): Promise<void> {
    const store = await cookies()
    store.delete(COOKIE_NAME)
}

/**
 * Short-lived state cookie used for the OAuth PKCE flow. We need to
 * persist the `code_verifier` + the original URL the user was on
 * between the `/login` redirect and the `/callback` request — same
 * sealing approach, different cookie name + tighter TTL.
 */
const FLOW_COOKIE_NAME = 'agent-console-oauth-flow'
const FLOW_COOKIE_TTL_SECONDS = 60 * 10 // 10 minutes

export interface OAuthFlowPayload {
    state: string
    codeVerifier: string
    /** Where to send the user after a successful login. */
    returnTo: string
}

export async function setOAuthFlow(payload: OAuthFlowPayload): Promise<void> {
    const sealed = await sealData(payload, { password: cookieSecret(), ttl: FLOW_COOKIE_TTL_SECONDS })
    const store = await cookies()
    store.set(FLOW_COOKIE_NAME, sealed, {
        httpOnly: true,
        sameSite: 'lax',
        secure: cookieSecure(),
        path: '/',
        maxAge: FLOW_COOKIE_TTL_SECONDS,
    })
}

export async function consumeOAuthFlow(): Promise<OAuthFlowPayload | null> {
    const store = await cookies()
    const raw = store.get(FLOW_COOKIE_NAME)?.value
    if (!raw) {
        return null
    }
    store.delete(FLOW_COOKIE_NAME)
    try {
        return await unsealData<OAuthFlowPayload>(raw, {
            password: cookieSecret(),
            ttl: FLOW_COOKIE_TTL_SECONDS,
        })
    } catch {
        return null
    }
}
