import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

type OrganizationMemberSnapshot = {
    verifiedEmails: ReadonlySet<string>
    unverifiedEmails: ReadonlySet<string>
    sandboxSenderBlocked: boolean
    expiresAt: number
}

export type BlockedRecipient = { readonly address: string; readonly unverifiedMember: boolean }

export type RecipientCheck =
    | { readonly organizationBlocked: true }
    | { readonly organizationBlocked: false; readonly blockedRecipients: BlockedRecipient[] }

const MAX_SNAPSHOT_AGE_MS = 60_000
const REFRESH_AGE_MS = MAX_SNAPSHOT_AGE_MS - 1_000

const normalizeEmail = (email: string): string => email.trim().toLowerCase()

export class OrganizationMembersService {
    private snapshots: LazyLoader<OrganizationMemberSnapshot>

    constructor(
        postgres: PostgresRouter,
        private now: () => number = Date.now
    ) {
        this.snapshots = new LazyLoader({
            name: 'sandbox_team_organization_members',
            refreshAgeMs: REFRESH_AGE_MS,
            refreshJitterMs: 0,
            bufferMs: 0,
            loader: async (teamIds) => {
                const expiresAt = this.now() + MAX_SNAPSHOT_AGE_MS
                const ids = [teamIds.map(Number)]
                const [{ rows }, blocks] = await Promise.all([
                    // Only an explicit false deactivates an organization, matching the web middleware.
                    postgres.query<{ team_id: number; email: string; is_email_verified: boolean }>(
                        PostgresUse.COMMON_WRITE,
                        `SELECT team.id AS team_id, users.email, users.is_email_verified
                         FROM posthog_team AS team
                         JOIN posthog_organization AS organization ON organization.id = team.organization_id
                         JOIN posthog_organizationmembership AS membership ON membership.organization_id = organization.id
                         JOIN posthog_user AS users ON users.id = membership.user_id
                         WHERE team.id = ANY($1::bigint[])
                           AND organization.is_active IS NOT FALSE
                           AND users.is_active = true`,
                        ids,
                        'fetch-sandbox-team-organization-members'
                    ),
                    postgres.query<{ team_id: number }>(
                        PostgresUse.COMMON_WRITE,
                        `SELECT team.id AS team_id
                         FROM posthog_team AS team
                         JOIN workflows_sandboxsenderorganizationblock AS block ON block.organization_id = team.organization_id
                         WHERE team.id = ANY($1::bigint[])`,
                        ids,
                        'fetch-sandbox-team-organization-blocks'
                    ),
                ])
                const blockedTeamIds = new Set(blocks.rows.map((row) => String(row.team_id)))
                const members = new Map(
                    teamIds.map((id) => [id, { verified: new Set<string>(), unverified: new Set<string>() }])
                )
                for (const row of rows) {
                    const { verified, unverified } = members.get(String(row.team_id))!
                    ;(row.is_email_verified === true ? verified : unverified).add(normalizeEmail(row.email))
                }
                return Object.fromEntries(
                    [...members].map(([id, { verified, unverified }]) => [
                        id,
                        {
                            verifiedEmails: verified,
                            unverifiedEmails: unverified,
                            sandboxSenderBlocked: blockedTeamIds.has(id),
                            expiresAt,
                        },
                    ])
                )
            },
        })
    }

    public async checkRecipients(teamId: number, recipients: string[]): Promise<RecipientCheck> {
        const snapshot = await this.getFreshSnapshot(String(teamId))
        if (snapshot.sandboxSenderBlocked) {
            return { organizationBlocked: true }
        }
        const blockedRecipients = recipients
            .filter((email) => !snapshot.verifiedEmails.has(normalizeEmail(email)))
            .map((address) => ({ address, unverifiedMember: snapshot.unverifiedEmails.has(normalizeEmail(address)) }))
        return { organizationBlocked: false, blockedRecipients }
    }

    // A snapshot older than a minute never decides a send: it is reloaded once, and a reload that
    // itself outlasts the minute fails the check rather than trusting stale membership.
    private async getFreshSnapshot(teamId: string): Promise<OrganizationMemberSnapshot> {
        let snapshot = await this.snapshots.get(teamId)
        if (snapshot && this.now() >= snapshot.expiresAt) {
            this.snapshots.markForRefresh(teamId)
            snapshot = await this.snapshots.get(teamId)
        }
        if (!snapshot) {
            throw new Error('Could not check organization members')
        }
        if (this.now() >= snapshot.expiresAt) {
            this.snapshots.markForRefresh(teamId)
            throw new Error('The organization member check expired')
        }
        return snapshot
    }
}
