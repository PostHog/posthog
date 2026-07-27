/**
 * `dogs` — a real in-process OAuth2 (auth-code + PKCE) IdP plus a bearer-
 * protected demo API, for hermetic e2e of identity linking. NOT production
 * code: it lives in the test harness and is the generic-`oauth2`-provider
 * fixture (no external network, deterministic, test-controllable).
 *
 * Endpoints:
 *   GET  /authorize  auto-approves, 302 → redirect_uri?code&state
 *   POST /token      auth_code (verifies PKCE S256 + client) & refresh grants
 *   GET  /api/dog    401 without a valid, unexpired, unrevoked bearer
 *   GET  /userinfo   { sub, email } (sub lets an identity-establishing provider
 *                    stamp a subject; email is the link-time cross-check)
 */

import { createHash, randomUUID } from 'node:crypto'
import http from 'node:http'
import { AddressInfo } from 'node:net'

export interface DogServerOptions {
    clientId?: string
    clientSecret?: string
    /** Access-token lifetime. Small (e.g. 1) to exercise refresh. Default 3600. */
    tokenTtlSeconds?: number
    /** Email returned by /userinfo. Default dog@posthog.com. */
    userEmail?: string
    /** Subject (`sub`) returned by /userinfo. Default dog-user-1. */
    userSub?: string
    /** Fixed listen port (for a standalone dev server). Default 0 (random, for tests). */
    port?: number
}

interface CodeRecord {
    codeChallenge: string
    redirectUri: string
    scope: string
}

interface TokenRecord {
    refreshToken: string
    expiresAt: number
    scope: string
}

export interface DogServer {
    baseUrl: string
    authorizeUrl: string
    tokenUrl: string
    apiUrl: string
    userinfoUrl: string
    /** Tokens the API will currently accept (test introspection). */
    activeTokens(): string[]
    /** Every GET /api/dog seen, with the bearer used. */
    dogCalls: Array<{ token: string }>
    revoke(token: string): void
    close(): Promise<void>
}

const CLIENT_ID = 'dogs-client'

export async function startDogServer(opts: DogServerOptions = {}): Promise<DogServer> {
    const clientId = opts.clientId ?? CLIENT_ID
    const clientSecret = opts.clientSecret
    const ttlMs = (opts.tokenTtlSeconds ?? 3600) * 1000
    const email = opts.userEmail ?? 'dog@posthog.com'
    const sub = opts.userSub ?? 'dog-user-1'

    const codes = new Map<string, CodeRecord>()
    const tokens = new Map<string, TokenRecord>()
    const refreshToToken = new Map<string, string>()
    const revoked = new Set<string>()
    const dogCalls: Array<{ token: string }> = []

    const sha256 = (s: string): string => createHash('sha256').update(s).digest('base64url')

    const readBody = (req: http.IncomingMessage): Promise<string> =>
        new Promise((resolve) => {
            let data = ''
            req.on('data', (c) => (data += c))
            req.on('end', () => resolve(data))
        })

    const issue = (scope: string): { access_token: string; refresh_token: string; expires_in: number } => {
        const access = `dog-at-${randomUUID()}`
        const refresh = `dog-rt-${randomUUID()}`
        tokens.set(access, { refreshToken: refresh, expiresAt: Date.now() + ttlMs, scope })
        refreshToToken.set(refresh, access)
        return { access_token: access, refresh_token: refresh, expires_in: Math.floor(ttlMs / 1000) }
    }

    const server = http.createServer(async (req, res) => {
        const url = new URL(req.url ?? '/', 'http://localhost')
        const send = (status: number, body: unknown): void => {
            res.writeHead(status, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify(body))
        }

        if (req.method === 'GET' && url.pathname === '/authorize') {
            const code = `dog-code-${randomUUID()}`
            codes.set(code, {
                codeChallenge: url.searchParams.get('code_challenge') ?? '',
                redirectUri: url.searchParams.get('redirect_uri') ?? '',
                scope: url.searchParams.get('scope') ?? '',
            })
            const redirect = new URL(url.searchParams.get('redirect_uri') ?? '')
            redirect.searchParams.set('code', code)
            redirect.searchParams.set('state', url.searchParams.get('state') ?? '')
            res.writeHead(302, { Location: redirect.toString() })
            res.end()
            return
        }

        if (req.method === 'POST' && url.pathname === '/token') {
            const params = new URLSearchParams(await readBody(req))
            if (
                params.get('client_id') !== clientId ||
                (clientSecret && params.get('client_secret') !== clientSecret)
            ) {
                send(401, { error: 'invalid_client' })
                return
            }
            const grant = params.get('grant_type')
            if (grant === 'authorization_code') {
                const rec = codes.get(params.get('code') ?? '')
                if (!rec) {
                    send(400, { error: 'invalid_grant' })
                    return
                }
                codes.delete(params.get('code') ?? '')
                // PKCE S256 check.
                const verifier = params.get('code_verifier') ?? ''
                if (rec.codeChallenge && sha256(verifier) !== rec.codeChallenge) {
                    send(400, { error: 'invalid_grant', error_description: 'pkce_mismatch' })
                    return
                }
                send(200, { token_type: 'bearer', scope: rec.scope, ...issue(rec.scope) })
                return
            }
            if (grant === 'refresh_token') {
                const rt = params.get('refresh_token') ?? ''
                const prevAccess = refreshToToken.get(rt)
                if (!prevAccess) {
                    send(400, { error: 'invalid_grant' })
                    return
                }
                const prev = tokens.get(prevAccess)
                tokens.delete(prevAccess) // rotate access
                refreshToToken.delete(rt)
                send(200, { token_type: 'bearer', scope: prev?.scope ?? '', ...issue(prev?.scope ?? '') })
                return
            }
            send(400, { error: 'unsupported_grant_type' })
            return
        }

        const bearer = (req.headers.authorization ?? '').replace(/^Bearer\s+/i, '')
        const tokenValid = (t: string): boolean => {
            const rec = tokens.get(t)
            return !!rec && !revoked.has(t) && rec.expiresAt > Date.now()
        }

        if (req.method === 'GET' && url.pathname === '/api/dog') {
            dogCalls.push({ token: bearer })
            if (!tokenValid(bearer)) {
                send(401, { error: 'unauthorized' })
                return
            }
            send(200, { fact: 'Dogs have three eyelids.', breed: 'corgi' })
            return
        }

        if (req.method === 'GET' && url.pathname === '/userinfo') {
            if (!tokenValid(bearer)) {
                send(401, { error: 'unauthorized' })
                return
            }
            send(200, { sub, email })
            return
        }

        send(404, { error: 'not_found' })
    })

    await new Promise<void>((resolve) => server.listen(opts.port ?? 0, '127.0.0.1', resolve))
    const port = (server.address() as AddressInfo).port
    const baseUrl = `http://127.0.0.1:${port}`

    return {
        baseUrl,
        authorizeUrl: `${baseUrl}/authorize`,
        tokenUrl: `${baseUrl}/token`,
        apiUrl: `${baseUrl}/api/dog`,
        userinfoUrl: `${baseUrl}/userinfo`,
        activeTokens: () => [...tokens.keys()].filter((t) => !revoked.has(t) && tokens.get(t)!.expiresAt > Date.now()),
        dogCalls,
        revoke: (t) => revoked.add(t),
        close: () => new Promise<void>((resolve) => server.close(() => resolve())),
    }
}
