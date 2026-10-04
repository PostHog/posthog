import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { TeamManager } from '~/common/utils/team-manager'

export class OrganizationMembersService {
    private members: LazyLoader<ReadonlySet<string>>

    constructor(
        postgres: PostgresRouter,
        private teamManager: TeamManager
    ) {
        this.members = new LazyLoader({
            name: 'organization_email_members',
            refreshAgeMs: 59_000,
            refreshJitterMs: 0,
            bufferMs: 0,
            loader: async (organizationIds) => {
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
                return members
            },
        })
    }

    public async getBlockedRecipients(teamId: number, recipients: string[]): Promise<string[]> {
        const team = await this.teamManager.getTeam(teamId)
        if (!team) {
            throw new Error('Could not identify the organization for this team')
        }
        const members = await this.members.get(team.organization_id)
        if (!members) {
            throw new Error('Could not check organization members')
        }
        return recipients.filter((email) => !members.has(email.trim().toLowerCase()))
    }
}
