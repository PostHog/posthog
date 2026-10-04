import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

type OrganizationMemberSnapshot = {
    emails: ReadonlySet<string>
    expiresAt: number
}

export class OrganizationMembersService {
    private members: LazyLoader<OrganizationMemberSnapshot>

    constructor(private postgres: PostgresRouter) {
        this.members = new LazyLoader({
            name: 'organization_email_members',
            refreshAgeMs: 59_000,
            refreshJitterMs: 0,
            bufferMs: 0,
            loader: async (organizationIds) => {
                const expiresAt = Date.now() + 60_000
                const { rows } = await postgres.query<{ organization_id: string; email: string }>(
                    PostgresUse.COMMON_WRITE,
                    `SELECT membership.organization_id, users.email
                     FROM posthog_organizationmembership AS membership
                     JOIN posthog_user AS users ON users.id = membership.user_id
                     WHERE membership.organization_id = ANY($1::uuid[])
                       AND users.is_active = true AND users.is_email_verified = true`,
                    [organizationIds],
                    'fetch-organization-email-members'
                )
                const members: Record<string, Set<string>> = Object.fromEntries(
                    organizationIds.map((id) => [id, new Set<string>()])
                )
                for (const row of rows) {
                    members[row.organization_id].add(row.email.trim().toLowerCase())
                }
                return Object.fromEntries(Object.entries(members).map(([id, emails]) => [id, { emails, expiresAt }]))
            },
        })
    }

    public async getBlockedRecipients(teamId: number, recipients: string[]): Promise<string[]> {
        const expiresAt = Date.now() + 60_000
        const {
            rows: [team],
        } = await this.postgres.query<{ organization_id: string }>(
            PostgresUse.COMMON_WRITE,
            'SELECT organization_id FROM posthog_team WHERE id = $1',
            [teamId],
            'fetch-sandbox-team-organization'
        )
        if (!team) {
            throw new Error('Could not identify the organization for this team')
        }
        let members = await this.members.get(team.organization_id)
        if (members && Date.now() >= members.expiresAt && Date.now() < expiresAt) {
            this.members.markForRefresh(team.organization_id)
            members = await this.members.get(team.organization_id)
        }
        if (!members) {
            throw new Error('Could not check organization members')
        }
        if (Date.now() >= Math.min(expiresAt, members.expiresAt)) {
            this.members.markForRefresh(team.organization_id)
            throw new Error('The organization member check expired')
        }
        return recipients.filter((email) => !members.emails.has(email.trim().toLowerCase()))
    }
}
