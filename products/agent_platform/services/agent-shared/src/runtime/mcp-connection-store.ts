/**
 * Resolves `spec.mcps[].connection` (a native `mcp_store` `MCPServerInstallation`)
 * into an upstream URL + bearer — the agent-level shared-credential path (one
 * connection, every asker). DB-direct against `posthogDb`, no Django HTTP:
 * read → decrypt → refresh-on-expiry → write-back, duplicating mcp_store/oauth.py.
 * `FOR UPDATE` serialises the shared row; cross-pod single-flight is deferred.
 */

import type { Pool } from 'pg'

import { EncryptedFields } from './encryption'
import type { HttpFetcher } from './http-client'
import { createLogger } from './logger'

export type McpConnectionResolution =
    | { kind: 'resolved'; url: string; bearer: string }
    /** No usable credential (missing or `needs_reauth`); the OWNER must reconnect. */
    | { kind: 'needs_reauth' }
    /** Owner disabled the installation (`is_enabled = false`). */
    | { kind: 'disabled' }
    /** No installation with this id for the agent's team. */
    | { kind: 'not_found' }

export interface McpConnectionStore {
    /** Resolve an installation (UUID, scoped to `teamId`) to URL + bearer,
     *  refreshing an expiring OAuth token in place. Throws
     *  `mcp_connection_refresh_failed` on a transient refresh failure. */
    resolve(connectionId: string, teamId: number): Promise<McpConnectionResolution>
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

interface OauthContext {
    tokenEndpoint: string
    clientId: string
    clientSecret?: string
}

interface TokenResponse {
    access_token: string
    refresh_token?: string
    expires_in?: number
}

const SELECT_INSTALLATION = `
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
     WHERE i.id = $1 AND i.team_id = $2`

/** Reads `mcp_store_mcpserverinstallation` (+ optional template) from the main
 *  DB. Pass the main-DB pool. Write-back needs UPDATE on that table. */
export class PgMcpConnectionStore implements McpConnectionStore {
    private readonly log = createLogger('mcp-connection-store')

    constructor(
        private readonly pool: Pool,
        private readonly encryption: EncryptedFields,
        private readonly http: HttpFetcher
    ) {}

    async resolve(connectionId: string, teamId: number): Promise<McpConnectionResolution> {
        const { rows } = await this.pool.query<InstallationRow>(SELECT_INSTALLATION, [connectionId, teamId])
        if (rows.length === 0) {
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
        const refreshed = await this.refresh(connectionId, teamId)
        return { kind: 'resolved', url: row.url, bearer: refreshed }
    }

    /** Refresh under a row lock, write back the rotated token, return it.
     *  Re-checks expiry after locking (another worker may have refreshed).
     *  Throws on transient failure; does NOT set `needs_reauth` (reserved for a
     *  hard refresh-token rejection by the connect flow). */
    private async refresh(connectionId: string, teamId: number): Promise<string> {
        const client = await this.pool.connect()
        try {
            await client.query('BEGIN')
            const { rows } = await client.query<InstallationRow>(`${SELECT_INSTALLATION} FOR UPDATE OF i`, [
                connectionId,
                teamId,
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
                return current
            }
            const refreshToken = asNonEmptyString(sensitive.refresh_token)
            if (!refreshToken) {
                throw new Error(`mcp_connection_refresh_failed: ${connectionId} (no refresh token)`)
            }
            const ctx = this.resolveOauthContext(row, sensitive)
            const token = await this.tokenRefreshRequest(ctx, refreshToken)

            // Preserve non-token leaves (dcr_client_id/secret, needs_reauth, …).
            const updated: Record<string, unknown> = { ...sensitive }
            updated.access_token = token.access_token
            updated.token_retrieved_at = String(Math.floor(Date.now() / 1000))
            updated.refresh_token = token.refresh_token ?? refreshToken
            if (token.expires_in !== undefined) {
                updated.expires_in = String(token.expires_in)
            }
            const encrypted = this.encryption.encryptJsonFieldValue(updated)
            await client.query(
                'UPDATE mcp_store_mcpserverinstallation SET sensitive_configuration = $1::jsonb, updated_at = NOW() WHERE id = $2',
                [JSON.stringify(encrypted), connectionId]
            )
            await client.query('COMMIT')
            this.log.info({ connection_id: connectionId }, 'mcp_connection.token_refreshed')
            return token.access_token
        } catch (err) {
            try {
                await client.query('ROLLBACK')
            } catch {
                // Original error wins; a rollback failure on a broken connection
                // is not separately actionable.
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
                const tokenEndpoint = asNonEmptyString((row.template_oauth_metadata ?? {}).token_endpoint)
                if (!tokenEndpoint) {
                    throw new Error('mcp_connection_refresh_failed: template missing token_endpoint')
                }
                return { tokenEndpoint, clientId: sharedClientId, clientSecret: asNonEmptyString(creds.client_secret) }
            }
        }
        const tokenEndpoint = asNonEmptyString((row.oauth_metadata ?? {}).token_endpoint)
        const clientId = asNonEmptyString(sensitive.dcr_client_id)
        if (!tokenEndpoint || !clientId) {
            throw new Error('mcp_connection_refresh_failed: missing oauth metadata or client_id')
        }
        return { tokenEndpoint, clientId, clientSecret: asNonEmptyString(sensitive.dcr_client_secret) }
    }

    private async tokenRefreshRequest(ctx: OauthContext, refreshToken: string): Promise<TokenResponse> {
        const body = new URLSearchParams({
            grant_type: 'refresh_token',
            refresh_token: refreshToken,
            client_id: ctx.clientId,
        })
        if (ctx.clientSecret) {
            body.set('client_secret', ctx.clientSecret)
        }
        const res = await this.http.fetch(ctx.tokenEndpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
            body: body.toString(),
        })
        if (!res.ok) {
            const text = await res.text().catch(() => '')
            throw new Error(`token_http_${res.status}: ${text.slice(0, 200)}`)
        }
        const json = (await res.json()) as TokenResponse
        if (!json.access_token) {
            throw new Error('token_no_access_token')
        }
        return json
    }
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
