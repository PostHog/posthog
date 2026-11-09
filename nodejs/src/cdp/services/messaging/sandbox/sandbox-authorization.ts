import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
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
        row = await withDeadline(
            db.transaction(PostgresUse.COMMON_WRITE, 'sandbox-email-authorization', async (tx) => {
                await db.query(
                    tx,
                    `SET LOCAL statement_timeout = ${AUTHORIZATION_TIMEOUT_MS}`,
                    undefined,
                    'sandbox-email-authorization'
                )
                const result = await db.query<AuthorizationRow>(
                    tx,
                    AUTHORIZATION_QUERY,
                    [teamId, recipient, tenantName],
                    'sandbox-email-authorization'
                )
                return result.rows[0]
            }),
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

async function withDeadline<T>(work: Promise<T>, timeoutMs: number): Promise<T> {
    let timer: NodeJS.Timeout | undefined
    const deadline = new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error(`timed out after ${timeoutMs} ms`)), timeoutMs)
    })
    try {
        return await Promise.race([work, deadline])
    } finally {
        clearTimeout(timer)
    }
}
