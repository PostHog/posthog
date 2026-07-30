import type { Pool } from 'pg'

import { EncryptedFields } from './encryption'
import type { HttpFetcher } from './http-client'
import { PgMcpConnectionStore } from './mcp-connection-store'

// 32-byte UTF-8 key — matches Django's ENCRYPTION_SALT_KEYS shape.
const KEY = '01234567890123456789012345678901'
const enc = new EncryptedFields(KEY)
const nowSec = Math.floor(Date.now() / 1000)
// Spec author / installation owner threaded into resolve (agent_revision.created_by_id).
const OWNER = 7

function fakeResponse(opts: { ok: boolean; status?: number; body?: unknown; text?: string }): Response {
    return {
        ok: opts.ok,
        status: opts.status ?? (opts.ok ? 200 : 400),
        json: async () => opts.body,
        text: async () => opts.text ?? '',
    } as unknown as Response
}

function makeFakeHttp(response: Response): HttpFetcher & { calls: Array<{ url: string; init?: RequestInit }> } {
    const calls: Array<{ url: string; init?: RequestInit }> = []
    return {
        calls,
        async fetch(input: string | URL, init?: RequestInit) {
            calls.push({ url: String(input), init })
            return response
        },
    }
}

type QueryLog = Array<{ sql: string; values: unknown[] }>
type QueryResult = { rows: Array<Record<string, unknown>> }

function makeFakePool(row: Record<string, unknown> | null): { pool: Pool; calls: QueryLog; writes: QueryLog } {
    const calls: QueryLog = []
    const writes: QueryLog = []
    const handle = (sql: string, values: unknown[]): QueryResult => {
        calls.push({ sql, values })
        const t = sql.trim()
        if (/^(BEGIN|COMMIT|ROLLBACK)/.test(t)) {
            return { rows: [] }
        }
        if (t.startsWith('UPDATE mcp_store_mcpserverinstallation')) {
            writes.push({ sql, values })
            return { rows: [] }
        }
        return { rows: row ? [row] : [] } // SELECT (read or FOR UPDATE)
    }
    const pool = {
        query: (sql: string, values: unknown[]) => Promise.resolve(handle(sql, values)),
        connect: () =>
            Promise.resolve({
                query: (sql: string, values: unknown[]) => Promise.resolve(handle(sql, values)),
                release: () => {},
            }),
    }
    return { pool: pool as unknown as Pool, calls, writes }
}

function oauthRow(
    opts: {
        expiring?: boolean
        needsReauth?: boolean
        isEnabled?: boolean
        noRefreshToken?: boolean
        secret?: string
        authMethod?: string
        resource?: string
    } = {}
): Record<string, unknown> {
    const sensitive: Record<string, unknown> = {
        access_token: 'tok-1',
        refresh_token: 'refresh-1',
        token_retrieved_at: String(opts.expiring ? nowSec - 7200 : nowSec),
        expires_in: '3600',
        dcr_client_id: 'client-1',
    }
    if (opts.noRefreshToken) {
        delete sensitive.refresh_token
    }
    if (opts.needsReauth) {
        sensitive.needs_reauth = 'True'
    }
    if (opts.secret) {
        sensitive.dcr_client_secret = opts.secret
    }
    if (opts.authMethod) {
        sensitive.dcr_token_endpoint_auth_method = opts.authMethod
    }
    return {
        url: 'https://mcp.example.com/mcp',
        auth_type: 'oauth',
        is_enabled: opts.isEnabled ?? true,
        sensitive_configuration: enc.encryptJsonFieldValue(sensitive),
        oauth_metadata: {
            token_endpoint: 'https://idp.example.com/token',
            ...(opts.resource ? { resource: opts.resource } : {}),
        },
        template_id: null,
        template_oauth_metadata: null,
        template_oauth_credentials: null,
    }
}

describe('PgMcpConnectionStore', () => {
    it('scopes the lookup to (connectionId, teamId, ownerUserId) — the IDOR boundary', async () => {
        // The owner (spec author) must be in the WHERE params; dropping it would let
        // a spec reference a connection owned by a different user in the same team.
        const { pool, calls } = makeFakePool(oauthRow())
        const store = new PgMcpConnectionStore(pool, enc, makeFakeHttp(fakeResponse({ ok: true })))
        await store.resolve('conn-1', 42, OWNER)
        expect(calls[0].values).toEqual(['conn-1', 42, OWNER])
    })

    it('fails closed on a null owner without touching the DB', async () => {
        // An unattributable spec (no created_by_id) cannot use a stored credential.
        const { pool, calls } = makeFakePool(oauthRow())
        const store = new PgMcpConnectionStore(pool, enc, makeFakeHttp(fakeResponse({ ok: true })))
        await expect(store.resolve('conn-1', 42, null)).resolves.toEqual({ kind: 'not_found' })
        expect(calls).toHaveLength(0)
    })

    it('resolves an api-key installation without refresh', async () => {
        const { pool, writes } = makeFakePool({
            url: 'https://mcp.example.com/mcp',
            auth_type: 'api_key',
            is_enabled: true,
            sensitive_configuration: enc.encryptJsonFieldValue({ api_key: 'key-1' }),
            oauth_metadata: {},
            template_id: null,
            template_oauth_metadata: null,
            template_oauth_credentials: null,
        })
        const http = makeFakeHttp(fakeResponse({ ok: true }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await expect(store.resolve('c', 1, OWNER)).resolves.toEqual({
            kind: 'resolved',
            url: 'https://mcp.example.com/mcp',
            bearer: 'key-1',
        })
        expect(http.calls).toHaveLength(0)
        expect(writes).toHaveLength(0)
    })

    it('resolves a non-expiring oauth token from the stored value', async () => {
        const { pool, writes } = makeFakePool(oauthRow({ expiring: false }))
        const http = makeFakeHttp(fakeResponse({ ok: true }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await expect(store.resolve('c', 1, OWNER)).resolves.toEqual({
            kind: 'resolved',
            url: 'https://mcp.example.com/mcp',
            bearer: 'tok-1',
        })
        expect(http.calls).toHaveLength(0)
        expect(writes).toHaveLength(0)
    })

    it('refreshes an expiring oauth token and writes the rotated token back', async () => {
        const { pool, writes } = makeFakePool(oauthRow({ expiring: true }))
        const http = makeFakeHttp(
            fakeResponse({ ok: true, body: { access_token: 'tok-2', refresh_token: 'refresh-2', expires_in: 1800 } })
        )
        const store = new PgMcpConnectionStore(pool, enc, http)
        const res = await store.resolve('c', 1, OWNER)
        expect(res).toEqual({
            kind: 'resolved',
            url: 'https://mcp.example.com/mcp',
            bearer: 'tok-2',
        })

        // Refresh hit the token endpoint with the refresh grant + client id.
        expect(http.calls).toHaveLength(1)
        expect(http.calls[0].url).toBe('https://idp.example.com/token')
        expect(String(http.calls[0].init?.body)).toContain('grant_type=refresh_token')
        expect(String(http.calls[0].init?.body)).toContain('client_id=client-1')

        // Wrote back, in the per-leaf-encrypted format Django/PostHog Code reads.
        expect(writes).toHaveLength(1)
        const written = enc.decryptJsonFieldValue(JSON.parse(writes[0].values[0] as string)) as Record<string, unknown>
        expect(written.access_token).toBe('tok-2')
        expect(written.refresh_token).toBe('refresh-2')
        expect(written.expires_in).toBe('1800')
        expect(written.dcr_client_id).toBe('client-1') // non-token leaves preserved
    })

    it('uses HTTP Basic auth for a confidential client (Django default when a secret is present)', async () => {
        const { pool } = makeFakePool(oauthRow({ expiring: true, secret: 'secret-1' }))
        const http = makeFakeHttp(fakeResponse({ ok: true, body: { access_token: 'tok-2', expires_in: 1800 } }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await store.resolve('c', 1, OWNER)
        const init = http.calls[0].init!
        expect((init.headers as Record<string, string>).Authorization).toBe(
            `Basic ${Buffer.from('client-1:secret-1').toString('base64')}`
        )
        // Basic → credentials live in the header, never the form body.
        const body = String(init.body)
        expect(body).not.toContain('client_secret=')
        expect(body).not.toContain('client_id=')
    })

    it('uses client_secret_post (creds in body) when the stored auth method says so', async () => {
        const { pool } = makeFakePool(
            oauthRow({ expiring: true, secret: 'secret-1', authMethod: 'client_secret_post' })
        )
        const http = makeFakeHttp(fakeResponse({ ok: true, body: { access_token: 'tok-2', expires_in: 1800 } }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await store.resolve('c', 1, OWNER)
        const init = http.calls[0].init!
        expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
        const body = String(init.body)
        expect(body).toContain('client_id=client-1')
        expect(body).toContain('client_secret=secret-1')
    })

    it('sends the resource parameter on refresh when the metadata pins one', async () => {
        const { pool } = makeFakePool(oauthRow({ expiring: true, resource: 'https://api.example.com' }))
        const http = makeFakeHttp(fakeResponse({ ok: true, body: { access_token: 'tok-2', expires_in: 1800 } }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await store.resolve('c', 1, OWNER)
        expect(String(http.calls[0].init?.body)).toContain('resource=https%3A%2F%2Fapi.example.com')
    })

    it('refuses a redirecting token endpoint (manual redirect) and flags needs_reauth', async () => {
        const { pool, writes } = makeFakePool(oauthRow({ expiring: true }))
        const http = makeFakeHttp(fakeResponse({ ok: false, status: 302, text: '' }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await expect(store.resolve('c', 1, OWNER)).rejects.toThrow(/mcp_connection_needs_reauth/)
        // Don't follow redirects (Django uses allow_redirects=False), and treat a
        // 3xx as a permanent misconfig → needs_reauth, not an endless retry.
        expect(http.calls[0].init?.redirect).toBe('manual')
        const written = enc.decryptJsonFieldValue(JSON.parse(writes[0].values[0] as string)) as Record<string, unknown>
        expect(written.needs_reauth).toBe('True')
    })

    it('does not persist a non-finite expires_in (IdP returned null)', async () => {
        const { pool, writes } = makeFakePool(oauthRow({ expiring: true }))
        const http = makeFakeHttp(fakeResponse({ ok: true, body: { access_token: 'tok-2', expires_in: null } }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await store.resolve('c', 1, OWNER)
        const written = enc.decryptJsonFieldValue(JSON.parse(writes[0].values[0] as string)) as Record<string, unknown>
        // Storing "null" NaN-poisons isTokenExpiring → pins the bearer as
        // never-refreshing. Keep the prior numeric value instead.
        expect(written.expires_in).not.toBe('null')
        expect(written.access_token).toBe('tok-2')
    })

    it('keeps the existing refresh token when the refresh response omits one', async () => {
        const { pool, writes } = makeFakePool(oauthRow({ expiring: true }))
        const http = makeFakeHttp(fakeResponse({ ok: true, body: { access_token: 'tok-2', expires_in: 1800 } }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await store.resolve('c', 1, OWNER)
        const written = enc.decryptJsonFieldValue(JSON.parse(writes[0].values[0] as string)) as Record<string, unknown>
        expect(written.refresh_token).toBe('refresh-1')
    })

    it('returns needs_reauth when the credential is flagged', async () => {
        const { pool } = makeFakePool(oauthRow({ needsReauth: true }))
        const store = new PgMcpConnectionStore(pool, enc, makeFakeHttp(fakeResponse({ ok: true })))
        await expect(store.resolve('c', 1, OWNER)).resolves.toEqual({ kind: 'needs_reauth' })
    })

    it('returns disabled when the installation is disabled', async () => {
        const { pool } = makeFakePool(oauthRow({ isEnabled: false }))
        const store = new PgMcpConnectionStore(pool, enc, makeFakeHttp(fakeResponse({ ok: true })))
        await expect(store.resolve('c', 1, OWNER)).resolves.toEqual({ kind: 'disabled' })
    })

    it('returns not_found when no row matches', async () => {
        const { pool } = makeFakePool(null)
        const store = new PgMcpConnectionStore(pool, enc, makeFakeHttp(fakeResponse({ ok: true })))
        await expect(store.resolve('c', 1, OWNER)).resolves.toEqual({ kind: 'not_found' })
    })

    it('flags needs_reauth (and stops retrying) on a permanent 4xx refresh rejection', async () => {
        const { pool, writes } = makeFakePool(oauthRow({ expiring: true }))
        const http = makeFakeHttp(fakeResponse({ ok: false, status: 400, text: 'invalid_grant' }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await expect(store.resolve('c', 1, OWNER)).rejects.toThrow(/mcp_connection_needs_reauth/)
        // Wrote needs_reauth back so the next resolve short-circuits instead of
        // re-hitting the token endpoint every session.
        expect(writes).toHaveLength(1)
        const written = enc.decryptJsonFieldValue(JSON.parse(writes[0].values[0] as string)) as Record<string, unknown>
        expect(written.needs_reauth).toBe('True')
    })

    it('flags needs_reauth (and stops retrying) when an expiring oauth token has no refresh token', async () => {
        const { pool, writes } = makeFakePool(oauthRow({ expiring: true, noRefreshToken: true }))
        const http = makeFakeHttp(fakeResponse({ ok: true }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await expect(store.resolve('c', 1, OWNER)).rejects.toThrow(/mcp_connection_needs_reauth/)
        // Nothing to refresh with → no token-endpoint call…
        expect(http.calls).toHaveLength(0)
        // …but needs_reauth is written back so the next resolve short-circuits
        // instead of re-acquiring the lock and rolling back every session.
        expect(writes).toHaveLength(1)
        const written = enc.decryptJsonFieldValue(JSON.parse(writes[0].values[0] as string)) as Record<string, unknown>
        expect(written.needs_reauth).toBe('True')
    })

    it('throws a transient refresh failure without flagging needs_reauth on a 5xx', async () => {
        const { pool, writes } = makeFakePool(oauthRow({ expiring: true }))
        const http = makeFakeHttp(fakeResponse({ ok: false, status: 503, text: 'upstream down' }))
        const store = new PgMcpConnectionStore(pool, enc, http)
        await expect(store.resolve('c', 1, OWNER)).rejects.toThrow(/mcp_connection_refresh_failed/)
        expect(writes).toHaveLength(0)
    })
})
