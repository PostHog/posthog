import { PostgresRouter } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

import { BoundedPrimaryLookup } from '../../utils/bounded-primary-lookup'

type OrganizationMemberSnapshot = {
    verifiedEmails: ReadonlySet<string>
    unverifiedEmails: ReadonlySet<string>
    expiresAt: number
}

export type BlockedRecipient = { readonly address: string; readonly unverifiedMember: boolean }

const MAX_SNAPSHOT_AGE_MS = 60_000
const REFRESH_AGE_MS = MAX_SNAPSHOT_AGE_MS - 1_000
const LOOKUP_TIMEOUT_MS = 3_000
const MAX_OPEN_LOOKUPS = 5

type MemberRow = { team_id: number; email: string; is_email_verified: boolean }

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

    public async getBlockedRecipients(
        teamId: number,
        recipients: string[],
        { fresh = false }: { fresh?: boolean } = {}
    ): Promise<BlockedRecipient[]> {
        const snapshot = fresh
            ? await this.loadUncachedSnapshot(String(teamId))
            : await this.getUnexpiredCachedSnapshot(String(teamId))
        return recipients
            .filter((email) => !snapshot.verifiedEmails.has(normalizeEmail(email)))
            .map((address) => ({ address, unverifiedMember: snapshot.unverifiedEmails.has(normalizeEmail(address)) }))
    }

    private async loadUncachedSnapshot(teamId: string): Promise<OrganizationMemberSnapshot> {
        const snapshot = (await this.loadSnapshots([teamId]))[teamId]
        if (this.now() >= snapshot.expiresAt) {
            throw new Error('The organization member check expired')
        }
        return snapshot
    }

    private async loadSnapshots(teamIds: string[]): Promise<Record<string, OrganizationMemberSnapshot>> {
        const expiresAt = this.now() + MAX_SNAPSHOT_AGE_MS
        const rows = await this.lookupMembers(teamIds.map(Number))
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
                { verifiedEmails: verified, unverifiedEmails: unverified, expiresAt },
            ])
        )
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

    private async getUnexpiredCachedSnapshot(teamId: string): Promise<OrganizationMemberSnapshot> {
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
