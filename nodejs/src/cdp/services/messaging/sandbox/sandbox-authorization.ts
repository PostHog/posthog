import { QueryResultRow } from 'pg'

import { PostgresRouter, PostgresUse, TransactionClient } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import { SandboxTenantMirror } from './sandbox-tenant-admission'

export const AUTHORIZATION_TIMEOUT_MS = 2_000

export type SandboxAuthorization =
    | {
          ok: true
          organizationId: string
          organizationName: string
          storedAddress: string
          tenant: SandboxTenantMirror
      }
    | {
          ok: false
          reason:
              | 'not_member'
              | 'ambiguous_member'
              | 'organization_blocked'
              | 'team_not_found'
              | 'authorization_unavailable'
      }

type AuthorizationRow = {
    organization_id: string
    organization_name: string
    organization_blocked: boolean
    member_emails: string[]
    sending_status: string | null
    synced_at: string | null
}

const AUTHORIZATION_QUERY = `
SELECT
    organization.id AS organization_id,
    organization.name AS organization_name,
    EXISTS (
        SELECT 1 FROM workflows_sandboxsenderorganizationblock AS block
        WHERE block.organization_id = organization.id
    ) AS organization_blocked,
    ARRAY(
        SELECT users.email
        FROM posthog_organizationmembership AS membership
        JOIN posthog_user AS users ON users.id = membership.user_id
        WHERE membership.organization_id = organization.id
          AND organization.is_active IS NOT FALSE
          AND users.is_active = true
          AND users.is_email_verified = true
          AND lower(trim(users.email)) = lower(trim($2))
    ) AS member_emails,
    tenant.sending_status,
    tenant.synced_at
FROM posthog_team AS team
JOIN posthog_organization AS organization ON organization.id = team.organization_id
LEFT JOIN workflows_sandboxsendertenantstate AS tenant ON tenant.tenant_name = $3
WHERE team.id = $1`

export async function readSandboxAuthorization(
    db: PostgresRouter,
    { teamId, recipient, tenantName }: { teamId: number; recipient: string; tenantName: string }
): Promise<SandboxAuthorization> {
    let row: AuthorizationRow | undefined
    try {
        ;[row] = await queryPrimaryBeforeDeadline<AuthorizationRow>(
            db,
            AUTHORIZATION_QUERY,
            [teamId, recipient, tenantName],
            AUTHORIZATION_TIMEOUT_MS
        )
    } catch (error) {
        logger.warn('Could not read sandbox email authorization', { teamId, error: String(error) })
        return { ok: false, reason: 'authorization_unavailable' }
    }
    if (!row) {
        return { ok: false, reason: 'team_not_found' }
    }
    if (row.organization_blocked) {
        return { ok: false, reason: 'organization_blocked' }
    }
    const storedAddress = pickStoredAddress(row.member_emails, recipient)
    if (typeof storedAddress !== 'string') {
        return { ok: false, reason: storedAddress.reason }
    }
    return {
        ok: true,
        organizationId: row.organization_id,
        organizationName: row.organization_name,
        storedAddress,
        tenant: {
            sendingStatus: row.sending_status,
            syncedAt: row.synced_at === null ? null : new Date(row.synced_at),
        },
    }
}

function pickStoredAddress(
    memberEmails: string[],
    recipient: string
): string | { reason: 'not_member' | 'ambiguous_member' } {
    const spellings = [...new Set(memberEmails.map((email) => email.trim()))]
    if (spellings.length === 0) {
        return { reason: 'not_member' }
    }
    if (spellings.length === 1) {
        return spellings[0]
    }
    return spellings.includes(recipient.trim()) ? recipient.trim() : { reason: 'ambiguous_member' }
}

// A connection that arrives after the deadline runs no SQL, and one still busy at the deadline is destroyed rather
// than returned to the pool, so a stalled database cannot pile abandoned reads onto the shared primary pool.
export async function queryPrimaryBeforeDeadline<Row extends QueryResultRow>(
    db: PostgresRouter,
    text: string,
    values: unknown[],
    timeoutMs: number,
    tag: string = 'sandbox-email-authorization'
): Promise<Row[]> {
    let expired = false
    let timer: NodeJS.Timeout | undefined
    const deadline = new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
            expired = true
            reject(new Error(`The ${tag} read passed its ${timeoutMs} ms deadline`))
        }, timeoutMs)
    })
    const connecting = db.connect(PostgresUse.COMMON_WRITE)
    connecting.then(
        (client) => {
            if (expired) {
                client.release()
            }
        },
        () => undefined
    )
    try {
        const client = await Promise.race([connecting, deadline])
        let failure: Error | undefined
        const onClientError = (error: Error): void => {
            failure = error
        }
        client.on('error', onClientError)
        const tx = new TransactionClient(PostgresUse.COMMON_WRITE, client)
        try {
            return await Promise.race([
                (async () => {
                    await db.query(tx, 'BEGIN', undefined, tag)
                    await db.query(tx, `SET LOCAL statement_timeout = ${timeoutMs}`, undefined, tag)
                    const { rows } = await db.query<Row>(tx, text, values, tag)
                    await db.query(tx, 'COMMIT', undefined, tag)
                    return rows
                })(),
                deadline,
            ])
        } catch (error) {
            failure ??= error as Error
            throw error
        } finally {
            client.removeListener('error', onClientError)
            client.release(failure)
        }
    } finally {
        clearTimeout(timer)
    }
}
