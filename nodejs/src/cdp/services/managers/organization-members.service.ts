import { PostgresRouter } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

import { BoundedPrimaryLookup } from '../../utils/bounded-primary-lookup'

type OrganizationMemberSnapshot = {
    // Normalized address to the address as the user stored it.
    verifiedEmails: ReadonlyMap<string, string>
    unverifiedEmails: ReadonlySet<string>
    sandboxSenderBlocked: boolean
    expiresAt: number
}

export type BlockedRecipient = { readonly address: string; readonly unverifiedMember: boolean }

// `deliverTo` holds the stored address of each allowed recipient, in the order the recipients came in.
export type RecipientCheck =
    | { readonly organizationBlocked: true }
    | { readonly organizationBlocked: false; readonly blocked: BlockedRecipient[]; readonly deliverTo: string[] }

const MAX_SNAPSHOT_AGE_MS = 60_000
const REFRESH_AGE_MS = MAX_SNAPSHOT_AGE_MS - 1_000
// The lookup is two indexed queries.
const LOOKUP_TIMEOUT_MS = 3_000
const MAX_OPEN_LOOKUPS = 5

type MemberRow = { team_id: number; email: string; is_email_verified: boolean }
type TeamLookup = { members: MemberRow[]; blockedTeamIds: ReadonlySet<string> }

const normalizeEmail = (email: string): string => email.trim().toLowerCase()

export class OrganizationMembersService {
    private snapshots: LazyLoader<OrganizationMemberSnapshot>
    private lookup: BoundedPrimaryLookup

    constructor(
        private postgres: PostgresRouter,
        private now: () => number = Date.now
    ) {
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
            loader: (teamIds) => this.loadSnapshots(teamIds),
        })
    }

    // `fresh` runs its own lookup, for the check right before delivery: a member removed or an
    // organization blocked while the send was prepared must not receive it, so neither the cached
    // snapshot nor a lookup another send started earlier may answer it.
    // The match ignores case, so delivery goes to the stored address rather than the supplied one.
    public async checkRecipients(
        teamId: number,
        recipients: string[],
        { fresh = false }: { fresh?: boolean } = {}
    ): Promise<RecipientCheck> {
        const snapshot = fresh
            ? await this.loadOwnSnapshot(String(teamId))
            : await this.getFreshSnapshot(String(teamId))
        if (snapshot.sandboxSenderBlocked) {
            return { organizationBlocked: true }
        }
        const blocked: BlockedRecipient[] = []
        const deliverTo: string[] = []
        for (const address of recipients) {
            const stored = snapshot.verifiedEmails.get(normalizeEmail(address))
            if (stored === undefined) {
                blocked.push({ address, unverifiedMember: snapshot.unverifiedEmails.has(normalizeEmail(address)) })
            } else {
                deliverTo.push(stored)
            }
        }
        return { organizationBlocked: false, blocked, deliverTo }
    }

    private async loadOwnSnapshot(teamId: string): Promise<OrganizationMemberSnapshot> {
        const snapshot = (await this.loadSnapshots([teamId]))[teamId]
        if (this.now() >= snapshot.expiresAt) {
            throw new Error('The organization member check expired')
        }
        return snapshot
    }

    private async loadSnapshots(teamIds: string[]): Promise<Record<string, OrganizationMemberSnapshot>> {
        const expiresAt = this.now() + MAX_SNAPSHOT_AGE_MS
        const { members: rows, blockedTeamIds } = await this.lookupTeams(teamIds.map(Number))
        const members = new Map(
            teamIds.map((id) => [id, { verified: new Map<string, string>(), unverified: new Set<string>() }])
        )
        for (const row of rows) {
            const { verified, unverified } = members.get(String(row.team_id))!
            if (row.is_email_verified === true) {
                verified.set(normalizeEmail(row.email), row.email.trim())
            } else {
                unverified.add(normalizeEmail(row.email))
            }
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
    }

    private async lookupTeams(teamIds: number[]): Promise<TeamLookup> {
        const tag = 'fetch-sandbox-team-organization-members'
        return await this.lookup.run(tag, async (tx) => {
            // Only an explicit false deactivates an organization, matching the web middleware.
            const members = await this.postgres.query<MemberRow>(
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
            const blocks = await this.postgres.query<{ team_id: number }>(
                tx,
                `SELECT team.id AS team_id
                 FROM posthog_team AS team
                 JOIN workflows_sandboxsenderorganizationblock AS block ON block.organization_id = team.organization_id
                 WHERE team.id = ANY($1::bigint[])`,
                [teamIds],
                'fetch-sandbox-team-organization-blocks'
            )
            return {
                members: members.rows,
                blockedTeamIds: new Set(blocks.rows.map((row) => String(row.team_id))),
            }
        })
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
