import { PostgresRouter } from '~/common/utils/db/postgres'

import { runTransactionBeforeDeadline } from '../../utils/deadline-transaction'

export type BlockedRecipient = { readonly address: string; readonly unverifiedMember: boolean }

// The lookup is one indexed join. A stalled one fails the check here instead of holding up every other
// send in the worker's batch, which waits for this invocation to finish. The deadline counts the wait for
// a pooled connection too; the statement timeout also stops the query on the server.
const LOOKUP_TIMEOUT_MS = 3_000

type MemberRow = { team_id: number; email: string; is_email_verified: boolean }

const normalizeEmail = (email: string): string => email.trim().toLowerCase()

export class OrganizationMembersService {
    constructor(private postgres: PostgresRouter) {}

    // Every call reads membership again, so a member removed a moment ago never receives a send.
    // Any error or a lookup past its deadline throws, and the caller skips the send.
    public async getBlockedRecipients(teamId: number, recipients: string[]): Promise<BlockedRecipient[]> {
        const rows = await this.lookupMembers(teamId)
        const verifiedEmails = new Set<string>()
        const unverifiedEmails = new Set<string>()
        for (const row of rows) {
            ;(row.is_email_verified === true ? verifiedEmails : unverifiedEmails).add(normalizeEmail(row.email))
        }
        return recipients
            .filter((email) => !verifiedEmails.has(normalizeEmail(email)))
            .map((address) => ({ address, unverifiedMember: unverifiedEmails.has(normalizeEmail(address)) }))
    }

    private async lookupMembers(teamId: number): Promise<MemberRow[]> {
        const tag = 'fetch-sandbox-team-organization-members'
        let timedOut = false
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<never>((_, reject) => {
            timer = setTimeout(() => {
                timedOut = true
                reject(new Error('The organization member lookup timed out'))
            }, LOOKUP_TIMEOUT_MS)
        })
        const lookup = runTransactionBeforeDeadline(
            this.postgres,
            tag,
            { reached: deadline.catch(() => undefined), hasPassed: () => timedOut },
            LOOKUP_TIMEOUT_MS,
            async (tx) => {
                // Only an explicit false deactivates an organization, matching the web middleware.
                const result = await this.postgres.query<MemberRow>(
                    tx,
                    `SELECT team.id AS team_id, users.email, users.is_email_verified
                 FROM posthog_team AS team
                 JOIN posthog_organization AS organization ON organization.id = team.organization_id
                 JOIN posthog_organizationmembership AS membership ON membership.organization_id = organization.id
                 JOIN posthog_user AS users ON users.id = membership.user_id
                 WHERE team.id = ANY($1::bigint[])
                   AND organization.is_active IS NOT FALSE
                   AND users.is_active = true`,
                    [[teamId]],
                    tag
                )
                return result.rows
            }
        )
        // A lookup that loses the race can still fail later, after nobody waits for it.
        lookup.catch(() => undefined)
        try {
            return await Promise.race([lookup, deadline])
        } finally {
            clearTimeout(timer)
        }
    }
}
