import { PostgresRouter } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

import { BoundedPrimaryLookup } from '../../utils/bounded-primary-lookup'

type OrganizationMemberSnapshot = {
    verifiedEmails: ReadonlySet<string>
    unverifiedEmails: ReadonlySet<string>
}

export type BlockedRecipient = { readonly address: string; readonly unverifiedMember: boolean }

const MAX_SNAPSHOT_AGE_MS = 60_000
const LOOKUP_TIMEOUT_MS = 3_000
// The loader stamps a snapshot when its lookup ends, and the lookup deadline ends every lookup within
// LOOKUP_TIMEOUT_MS of reading, so no cached snapshot is older than MAX_SNAPSHOT_AGE_MS.
const REFRESH_AGE_MS = MAX_SNAPSHOT_AGE_MS - LOOKUP_TIMEOUT_MS
const MAX_OPEN_LOOKUPS = 5
const MAX_CACHED_TEAMS = 10_000

type MemberRow = { team_id: number; email: string; is_email_verified: boolean | null }

const normalizeEmail = (email: string): string => email.trim().toLowerCase()

const blockedBy = (snapshot: OrganizationMemberSnapshot, recipients: string[]): BlockedRecipient[] =>
    recipients
        .filter((email) => !snapshot.verifiedEmails.has(normalizeEmail(email)))
        .map((address) => ({ address, unverifiedMember: snapshot.unverifiedEmails.has(normalizeEmail(address)) }))

export class OrganizationMembersService {
    private snapshots: LazyLoader<OrganizationMemberSnapshot>
    private lookup: BoundedPrimaryLookup

    constructor(private postgres: PostgresRouter) {
        this.lookup = new BoundedPrimaryLookup(postgres, {
            name: 'organization member',
            timeoutMs: LOOKUP_TIMEOUT_MS,
            maxOpen: MAX_OPEN_LOOKUPS,
        })
        this.snapshots = new LazyLoader({
            name: 'sandbox_team_organization_members',
            refreshAgeMs: REFRESH_AGE_MS,
            refreshJitterMs: 0,
            bufferMs: 0,
            maxSize: MAX_CACHED_TEAMS,
            loader: (teamIds) => this.loadSnapshots(teamIds),
        })
    }

    // A cached snapshot can be up to a minute behind a member who just joined or verified, so a cached
    // block is checked again fresh. A fresh block marks the cache stale, so the next cached check sees it.
    public async getBlockedRecipients(
        teamId: number,
        recipients: string[],
        { fresh }: { fresh: boolean }
    ): Promise<BlockedRecipient[]> {
        const id = String(teamId)
        if (!fresh) {
            const cached = await this.snapshots.get(id)
            if (!cached) {
                throw new Error('Could not check organization members')
            }
            const blocked = blockedBy(cached, recipients)
            if (!blocked.length) {
                return blocked
            }
        }
        const blocked = blockedBy((await this.loadSnapshots([id]))[id], recipients)
        if (!fresh || blocked.length) {
            this.snapshots.markForRefresh(id)
        }
        return blocked
    }

    private async loadSnapshots(teamIds: string[]): Promise<Record<string, OrganizationMemberSnapshot>> {
        const rows = await this.lookupMembers(teamIds.map(Number))
        const members = new Map(
            teamIds.map((id) => [id, { verifiedEmails: new Set<string>(), unverifiedEmails: new Set<string>() }])
        )
        for (const row of rows) {
            const { verifiedEmails, unverifiedEmails } = members.get(String(row.team_id))!
            ;(row.is_email_verified === true ? verifiedEmails : unverifiedEmails).add(normalizeEmail(row.email))
        }
        return Object.fromEntries(members)
    }

    private async lookupMembers(teamIds: number[]): Promise<MemberRow[]> {
        const tag = 'fetch-sandbox-team-organization-members'
        return await this.lookup.run(tag, async (tx) => {
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
                [teamIds],
                tag
            )
            return result.rows
        })
    }
}
