/**
 * IdentityAdminStore — read + lifecycle surface over the agent's end-users and
 * their linked credentials, for the authoring/console UI (proxied through the
 * janitor + Django `AgentApplicationViewSet`).
 *
 * Deliberately KEYLESS: it joins `agent_user` ⋈ `agent_identity_credential` and
 * returns connection *metadata only* — it never reads `encrypted_credentials`
 * and never constructs `EncryptedFields`. The janitor must not hold the
 * decryption key (least privilege), so the runtime `PgIdentityCredentialStore`
 * (which decrypts) stays out of the janitor; this store covers what the console
 * needs without it. `revokeConnection` is the same state flip as
 * `PgIdentityCredentialStore.revoke`, but scoped by `(team_id, application_id)`
 * for defence-in-depth tenancy — `application_id` is already a tenant-unique
 * UUID, but the janitor path carries `team_id` too, so we enforce both and a
 * mismatched pair fails closed rather than crossing a team boundary.
 */

import type { Pool } from 'pg'

/** A linked external identity, metadata only — no credential material. */
export interface AdminConnection {
    id: string
    provider: string
    scopes: string[]
    state: string
    subject: string | null
    access_expires_at: string | null
    created_at: string
    updated_at: string
    revoked_at: string | null
}

/** An agent end-user plus their linked connections. */
export interface AdminUserWithConnections {
    id: string
    principal_kind: string
    principal_id: string
    metadata: Record<string, unknown> | null
    created_at: string
    connections: AdminConnection[]
}

interface JoinedRow {
    user_id: string
    principal_kind: string
    principal_id: string
    metadata: unknown
    user_created_at: Date
    conn_id: string | null
    provider: string | null
    scopes: string[] | null
    state: string | null
    subject: string | null
    access_expires_at: Date | null
    conn_created_at: Date | null
    conn_updated_at: Date | null
    revoked_at: Date | null
}

export class PgIdentityAdminStore {
    constructor(private readonly pool: Pool) {}

    /**
     * Every `agent_user` for a (team, application), each with its connections
     * (active or revoked). Users with no links are included (LEFT JOIN). Ordered
     * newest user first, oldest connection first. Scoped by `team_id` too so a
     * mismatched team/application pair returns nothing instead of crossing
     * tenants.
     */
    async listUsersWithConnections(teamId: number, applicationId: string): Promise<AdminUserWithConnections[]> {
        const r = await this.pool.query<JoinedRow>(
            `SELECT u.id                  AS user_id,
                    u.principal_kind      AS principal_kind,
                    u.principal_id        AS principal_id,
                    u.metadata            AS metadata,
                    u.created_at          AS user_created_at,
                    c.id                  AS conn_id,
                    c.provider            AS provider,
                    c.scopes              AS scopes,
                    c.state               AS state,
                    c.subject             AS subject,
                    c.access_expires_at   AS access_expires_at,
                    c.created_at          AS conn_created_at,
                    c.updated_at          AS conn_updated_at,
                    c.revoked_at          AS revoked_at
               FROM agent_user u
               LEFT JOIN agent_identity_credential c ON c.agent_user_id = u.id
              WHERE u.team_id = $1 AND u.application_id = $2
              ORDER BY u.created_at DESC, c.created_at ASC NULLS FIRST`,
            [teamId, applicationId]
        )

        const byUser = new Map<string, AdminUserWithConnections>()
        for (const row of r.rows) {
            let user = byUser.get(row.user_id)
            if (!user) {
                user = {
                    id: row.user_id,
                    principal_kind: row.principal_kind,
                    principal_id: row.principal_id,
                    metadata: (row.metadata as Record<string, unknown>) ?? null,
                    created_at: row.user_created_at.toISOString(),
                    connections: [],
                }
                byUser.set(row.user_id, user)
            }
            if (row.conn_id) {
                user.connections.push({
                    id: row.conn_id,
                    provider: row.provider ?? '',
                    scopes: row.scopes ?? [],
                    state: row.state ?? 'active',
                    subject: row.subject,
                    access_expires_at: row.access_expires_at ? row.access_expires_at.toISOString() : null,
                    created_at: row.conn_created_at ? row.conn_created_at.toISOString() : '',
                    updated_at: row.conn_updated_at ? row.conn_updated_at.toISOString() : '',
                    revoked_at: row.revoked_at ? row.revoked_at.toISOString() : null,
                })
            }
        }
        return [...byUser.values()]
    }

    /**
     * Revoke one active link (state → revoked, kept for audit). Scoped by
     * `(team_id, application_id)` so a leaked agent_user_id — or a mismatched
     * team/application pair — can't revoke another tenant's row. Returns true
     * when a row was flipped, false if there was nothing active to revoke.
     */
    async revokeConnection(
        teamId: number,
        applicationId: string,
        agentUserId: string,
        provider: string
    ): Promise<boolean> {
        const r = await this.pool.query(
            `UPDATE agent_identity_credential
                SET state = 'revoked', revoked_at = NOW(), updated_at = NOW()
              WHERE team_id = $1 AND application_id = $2 AND agent_user_id = $3 AND provider = $4 AND state = 'active'`,
            [teamId, applicationId, agentUserId, provider]
        )
        return (r.rowCount ?? 0) > 0
    }
}
