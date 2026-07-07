/**
 * Resolves `spec.mcps[].connection` (a native `mcp_store` `MCPServerInstallation`)
 * into an upstream URL + bearer — the agent-level shared-credential path (one
 * connection, every asker). DB-direct against `posthogDb`, no Django HTTP:
 * read → decrypt → refresh-on-expiry → write-back, duplicating mcp_store/oauth.py.
 * `FOR UPDATE` serialises the shared row; cross-pod single-flight is deferred.
 */

import type { Pool, PoolClient } from 'pg'

import { EncryptedFields } from './encryption'
import type { HttpFetcher } from './http-client'
import { createLogger } from './logger'

export type McpConnectionResolution =
    | {
          kind: 'resolved'
          url: string
          bearer: string
      }
    /** No usable credential (missing or `needs_reauth`); the OWNER must reconnect. */
    | { kind: 'needs_reauth' }
    /** Owner disabled the installation (`is_enabled = false`). */
    | { kind: 'disabled' }
    /** No installation for this id + team + owning user. The IDOR boundary: an
     *  installation owned by a different user (even same team) is `not_found`, so a
     *  spec author can only use a connection whose credential they own. */
    | { kind: 'not_found' }

export interface McpConnectionStore {
    /** Resolve an installation (scoped to `teamId` AND `ownerUserId`) to URL +
     *  bearer, refreshing an expiring OAuth token. `ownerUserId` is the spec
     *  author; a null owner fails closed to `not_found`. Throws
     *  `mcp_connection_refresh_failed` on a transient refresh failure. */
    resolve(connectionId: string, teamId: number, ownerUserId: number | null): Promise<McpConnectionResolution>
}

interface InstallationRow {
    url: string
    auth_type: string
    is_enabled: boolean
    sensitive_configuration: unknown
    oauth_metadata: Record<string, unknown> | null
    template_id: string | null
    template_oauth_metadata: Record<string, unknown> | null
    template_oauth_credentials: unknown
}

type TokenEndpointAuthMethod = 'client_secret_basic' | 'client_secret_post' | 'none'

interface OauthContext {
    tokenEndpoint: string
    clientId: string
    clientSecret?: string
    /** How the client authenticates to the token endpoint. Mirrors Django's
     *  per-installation `(dcr_)token_endpoint_auth_method`; defaults to
     *  `client_secret_basic` when a secret is present, else `none`. */
    authMethod: TokenEndpointAuthMethod
    /** RFC 8707 resource indicator from the OAuth metadata. Sent on refresh when
     *  the IdP audience-pins tokens (Entra, Auth0-with-audience) — omitting it
     *  400s the refresh on those servers. */
    resource?: string
}

interface TokenResponse {
    access_token: string
    refresh_token?: string
    expires_in?: number
}

export const SELECT_INSTALLATION = `
    SELECT i.url,
           i.auth_type,
           i.is_enabled,
           i.sensitive_configuration,
           i.oauth_metadata,
           i.template_id,
           t.oauth_metadata AS template_oauth_metadata,
           t.oauth_credentials AS template_oauth_credentials
      FROM mcp_store_mcpserverinstallation i
      LEFT JOIN mcp_store_mcpservertemplate t ON t.id = i.template_id
     WHERE i.id = $1 AND i.team_id = $2 AND i.user_id = $3`

/** Reads `mcp_store_mcpserverinstallation` (+ optional template) from the main
 *  DB. Pass the main-DB pool. Write-back needs UPDATE on that table. */
export class PgMcpConnectionStore implements McpConnectionStore {
    private readonly log = createLogger('mcp-connection-store')

    constructor(
        private readonly pool: Pool,
        private readonly encryption: EncryptedFields,
        private readonly http: HttpFetcher
    ) {}

    async resolve(connectionId: string, teamId: number, ownerUserId: number | null): Promise<McpConnectionResolution> {
        // Fail closed: a spec with no resolvable author cannot use a stored
        // credential. Short-circuit before touching the DB.
        if (ownerUserId == null) {
            // Greppable signal: owner-scoping turns a live agent whose author
            // can't be resolved into a not_found. Surface it so affected agents
            // can be found in logs instead of failing silently mid-session.
            this.log.warn({ connection_id: connectionId, team_id: teamId }, 'mcp_connection.resolve_null_author')
            return { kind: 'not_found' }
        }
        const { rows } = await this.pool.query<InstallationRow>(SELECT_INSTALLATION, [
            connectionId,
            teamId,
            ownerUserId,
        ])
        if (rows.length === 0) {
            // Distinguish "genuinely absent" (a normal not_found) from "exists
            // but owned by another team member" — the latter is a live agent the
            // owner-scoping tightening just broke, worth surfacing for an audit.
            const probe = await this.pool.query(
                'SELECT 1 FROM mcp_store_mcpserverinstallation WHERE id = $1 AND team_id = $2',
                [connectionId, teamId]
            )
            if (probe.rows.length > 0) {
                this.log.warn(
                    { connection_id: connectionId, team_id: teamId, owner_user_id: ownerUserId },
                    'mcp_connection.resolve_owner_mismatch'
                )
            }
            return { kind: 'not_found' }
        }
        const row = rows[0]
        if (!row.is_enabled) {
            return { kind: 'disabled' }
        }
        const sensitive = this.decryptJsonObject(row.sensitive_configuration)
        if (isPyTrue(sensitive.needs_reauth)) {
            return { kind: 'needs_reauth' }
        }

        if (row.auth_type === 'api_key') {
            const apiKey = asNonEmptyString(sensitive.api_key)
            if (!apiKey) {
                return { kind: 'needs_reauth' }
            }
            return { kind: 'resolved', url: row.url, bearer: apiKey }
        }

        // OAuth: use the stored access token, refreshing first if it's expiring.
        const accessToken = asNonEmptyString(sensitive.access_token)
        if (!accessToken) {
            return { kind: 'needs_reauth' }
        }
        if (!isTokenExpiring(sensitive)) {
            return { kind: 'resolved', url: row.url, bearer: accessToken }
        }
        const refreshed = await this.refresh(connectionId, teamId, ownerUserId)
        return { kind: 'resolved', url: row.url, bearer: refreshed }
    }

    /** Refresh under a row lock, write back the rotated token, return it.
     *  Re-checks expiry after locking (another worker may have refreshed). On a
     *  PERMANENT failure (4xx except 429 — the refresh token/client is rejected)
     *  flags `needs_reauth` in the SAME transaction so the next session
     *  short-circuits to "owner must reconnect" instead of re-hitting the IdP on
     *  every run; a TRANSIENT failure (5xx / 429 / network) rolls back so the
     *  next session retries. */
    private async refresh(connectionId: string, teamId: number, ownerUserId: number): Promise<string> {
        const client = await this.pool.connect()
        let committed = false
        try {
            await client.query('BEGIN')
            // The FOR UPDATE row lock below is held across the external token-
            // endpoint call, so a concurrent refresh for the same connection
            // would otherwise block up to the fetch timeout waiting on it. Fail
            // fast on lock acquisition instead of piling connections behind it.
            await client.query("SET LOCAL lock_timeout = '3s'")
            const { rows } = await client.query<InstallationRow>(`${SELECT_INSTALLATION} FOR UPDATE OF i`, [
                connectionId,
                teamId,
                ownerUserId,
            ])
            if (rows.length === 0) {
                throw new Error(`mcp_connection_refresh_failed: ${connectionId} (row vanished)`)
            }
            const row = rows[0]
            const sensitive = this.decryptJsonObject(row.sensitive_configuration)
            const current = asNonEmptyString(sensitive.access_token)
            // Another worker may have refreshed while we waited for the lock.
            if (current && !isTokenExpiring(sensitive)) {
                await client.query('COMMIT')
                committed = true
                return current
            }
            const refreshToken = asNonEmptyString(sensitive.refresh_token)
            if (!refreshToken) {
                // No refresh token (e.g. an OAuth install via DCR that never
                // issued one) + an expiring access token fails identically on
                // every future session. Flag `needs_reauth` in the SAME locked
                // transaction — exactly like the permanent-HTTP-rejection path
                // below — so `resolve()` short-circuits to "owner must reconnect"
                // next run instead of re-acquiring the lock and rolling back each
                // time.
                await this.writeSensitive(client, connectionId, { ...sensitive, needs_reauth: true })
                await client.query('COMMIT')
                committed = true
                this.log.warn({ connection_id: connectionId }, 'mcp_connection.no_refresh_token_needs_reauth')
                throw new Error(`mcp_connection_needs_reauth: ${connectionId} (no refresh token)`)
            }
            const ctx = this.resolveOauthContext(row, sensitive)

            let token: TokenResponse
            try {
                token = await this.tokenRefreshRequest(ctx, refreshToken)
            } catch (err) {
                // A permanent rejection (revoked/invalid refresh token) fails the
                // same way on every future session — flag `needs_reauth` so
                // `resolve()` short-circuits next time instead of burning a
                // token-endpoint call each run. Transient failures fall through to
                // the outer catch → rollback → retry on the next session.
                if (err instanceof TokenRefreshHttpError && err.permanent) {
                    await this.writeSensitive(client, connectionId, { ...sensitive, needs_reauth: true })
                    await client.query('COMMIT')
                    committed = true
                    this.log.warn(
                        { connection_id: connectionId, status: err.status },
                        'mcp_connection.refresh_rejected_needs_reauth'
                    )
                    throw new Error(`mcp_connection_needs_reauth: ${connectionId} (refresh rejected: ${err.status})`)
                }
                throw err
            }

            // Preserve non-token leaves (dcr_client_id/secret, …).
            const updated: Record<string, unknown> = { ...sensitive }
            updated.access_token = token.access_token
            updated.token_retrieved_at = String(Math.floor(Date.now() / 1000))
            updated.refresh_token = token.refresh_token ?? refreshToken
            // Only persist a real number. An IdP returning `expires_in: null`
            // would otherwise store "null", which `Number()`-coerces to NaN and
            // pins the bearer as never-refreshing (isTokenExpiring bails on NaN).
            if (typeof token.expires_in === 'number' && Number.isFinite(token.expires_in)) {
                updated.expires_in = String(token.expires_in)
            }
            await this.writeSensitive(client, connectionId, updated)
            await client.query('COMMIT')
            committed = true
            this.log.info({ connection_id: connectionId }, 'mcp_connection.token_refreshed')
            return token.access_token
        } catch (err) {
            if (!committed) {
                try {
                    await client.query('ROLLBACK')
                } catch {
                    // Original error wins; a rollback failure on a broken
                    // connection is not separately actionable.
                }
            }
            if (err instanceof Error && err.message.startsWith('mcp_connection_')) {
                throw err
            }
            throw new Error(
                `mcp_connection_refresh_failed: ${connectionId} (${err instanceof Error ? err.message : String(err)})`
            )
        } finally {
            client.release()
        }
    }

    /** Re-encrypt + write the full `sensitive_configuration` jsonb (per-leaf
     *  Fernet) within the caller's transaction. */
    private async writeSensitive(
        client: PoolClient,
        connectionId: string,
        sensitive: Record<string, unknown>
    ): Promise<void> {
        const encrypted = this.encryption.encryptJsonFieldValue(sensitive)
        await client.query(
            'UPDATE mcp_store_mcpserverinstallation SET sensitive_configuration = $1::jsonb, updated_at = NOW() WHERE id = $2',
            [JSON.stringify(encrypted), connectionId]
        )
    }

    /** Decrypt a jsonb `EncryptedJSONField` column into a plain object (string
     *  leaves). Tolerant of a text column (JSON string) too. */
    private decryptJsonObject(value: unknown): Record<string, unknown> {
        let parsed = value
        if (typeof parsed === 'string') {
            try {
                parsed = JSON.parse(parsed)
            } catch {
                return {}
            }
        }
        const decrypted = this.encryption.decryptJsonFieldValue(parsed)
        if (decrypted === null || typeof decrypted !== 'object' || Array.isArray(decrypted)) {
            return {}
        }
        return decrypted as Record<string, unknown>
    }

    /** Mirror of `resolve_installation_oauth_context`: shared-creds template uses
     *  the template's metadata+client; else the installation's metadata+client. */
    private resolveOauthContext(row: InstallationRow, sensitive: Record<string, unknown>): OauthContext {
        if (row.template_id) {
            const creds = this.decryptJsonObject(row.template_oauth_credentials)
            const sharedClientId = asNonEmptyString(creds.client_id)
            if (sharedClientId) {
                const meta = row.template_oauth_metadata ?? {}
                const tokenEndpoint = asNonEmptyString(meta.token_endpoint)
                if (!tokenEndpoint) {
                    throw new Error('mcp_connection_refresh_failed: template missing token_endpoint')
                }
                const clientSecret = asNonEmptyString(creds.client_secret)
                return {
                    tokenEndpoint,
                    clientId: sharedClientId,
                    clientSecret,
                    authMethod: credentialAuthMethod(creds.token_endpoint_auth_method, clientSecret),
                    resource: asNonEmptyString(meta.resource),
                }
            }
        }
        const meta = row.oauth_metadata ?? {}
        const tokenEndpoint = asNonEmptyString(meta.token_endpoint)
        const clientId = asNonEmptyString(sensitive.dcr_client_id)
        if (!tokenEndpoint || !clientId) {
            throw new Error('mcp_connection_refresh_failed: missing oauth metadata or client_id')
        }
        const clientSecret = asNonEmptyString(sensitive.dcr_client_secret)
        return {
            tokenEndpoint,
            clientId,
            clientSecret,
            authMethod: credentialAuthMethod(sensitive.dcr_token_endpoint_auth_method, clientSecret),
            resource: asNonEmptyString(meta.resource),
        }
    }

    private async tokenRefreshRequest(ctx: OauthContext, refreshToken: string): Promise<TokenResponse> {
        const body = new URLSearchParams({ grant_type: 'refresh_token', refresh_token: refreshToken })
        if (ctx.resource) {
            body.set('resource', ctx.resource)
        }
        const headers: Record<string, string> = {
            'Content-Type': 'application/x-www-form-urlencoded',
            Accept: 'application/json',
        }
        // Mirror Django's `_token_request_auth`: basic → credentials in the
        // Authorization header (client_id NOT in the body); post → both in the
        // body; none → just client_id. The method comes from the stored
        // `(dcr_)token_endpoint_auth_method` (Django defaults a confidential
        // client to basic — sending creds in the body 401s those servers).
        if (ctx.authMethod === 'client_secret_basic') {
            if (!ctx.clientSecret) {
                throw new Error('mcp_connection_refresh_failed: missing client_secret for client_secret_basic')
            }
            headers.Authorization = `Basic ${Buffer.from(`${ctx.clientId}:${ctx.clientSecret}`).toString('base64')}`
        } else {
            body.set('client_id', ctx.clientId)
            if (ctx.authMethod === 'client_secret_post') {
                if (!ctx.clientSecret) {
                    throw new Error('mcp_connection_refresh_failed: missing client_secret for client_secret_post')
                }
                body.set('client_secret', ctx.clientSecret)
            }
        }
        const res = await this.http.fetch(ctx.tokenEndpoint, {
            method: 'POST',
            headers,
            body: body.toString(),
            // Don't follow redirects (Django uses allow_redirects=False); a token
            // endpoint that 3xxes is misconfigured — treated as permanent below.
            redirect: 'manual',
        })
        if (res.status >= 300 && res.status < 400) {
            throw new TokenRefreshHttpError(res.status, 'token endpoint redirected')
        }
        if (!res.ok) {
            const text = await res.text().catch(() => '')
            throw new TokenRefreshHttpError(res.status, text)
        }
        const json = (await res.json()) as TokenResponse
        if (!json.access_token) {
            throw new Error('token_no_access_token')
        }
        return json
    }
}

/**
 * Non-2xx from the upstream OAuth token endpoint. `permanent` marks a 4xx
 * (except 429) — the refresh token/client is rejected and retrying won't help,
 * so the caller flags `needs_reauth`. 5xx / 429 are transient (retry next
 * session).
 */
class TokenRefreshHttpError extends Error {
    constructor(
        readonly status: number,
        bodyText: string
    ) {
        super(`token_http_${status}: ${bodyText.slice(0, 200)}`)
        this.name = 'TokenRefreshHttpError'
    }

    get permanent(): boolean {
        // 3xx (token endpoint redirected) is a permanent misconfig; 4xx except
        // 429 is a hard credential rejection. Both → needs_reauth. 5xx / 429 are
        // transient and retried next session.
        return this.status >= 300 && this.status < 500 && this.status !== 429
    }
}

const SUPPORTED_AUTH_METHODS: ReadonlySet<string> = new Set(['none', 'client_secret_post', 'client_secret_basic'])

/** Mirror of Django `_credential_auth_method`: use the stored method when it's a
 *  supported value, else default to `client_secret_basic` for a confidential
 *  client (secret present) and `none` otherwise. */
function credentialAuthMethod(stored: unknown, clientSecret: string | undefined): TokenEndpointAuthMethod {
    if (typeof stored === 'string' && SUPPORTED_AUTH_METHODS.has(stored)) {
        return stored as TokenEndpointAuthMethod
    }
    return clientSecret ? 'client_secret_basic' : 'none'
}

function asNonEmptyString(v: unknown): string | undefined {
    return typeof v === 'string' && v.length > 0 ? v : undefined
}

/** Django encrypts bools as `str(value)` → "True"/"False", so a decrypted leaf
 *  is the string "True". Match that (or a real bool) — not a "False" string. */
function isPyTrue(v: unknown): boolean {
    return v === true || v === 'True'
}

/** Mirror of `is_token_expiring`: refresh past 50% of lifetime. Leaves are
 *  strings after decrypt, so coerce. */
function isTokenExpiring(sensitive: Record<string, unknown>): boolean {
    const retrievedAt = Number(sensitive.token_retrieved_at ?? 0)
    const expiresIn = Number(sensitive.expires_in ?? 0)
    if (!retrievedAt || !expiresIn || Number.isNaN(retrievedAt) || Number.isNaN(expiresIn)) {
        return false
    }
    return Date.now() / 1000 > retrievedAt + expiresIn / 2
}
