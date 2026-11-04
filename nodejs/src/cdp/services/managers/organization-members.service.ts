import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

import { DeadlineSlots } from '../../utils/deadline-slots'

type OrganizationMemberSnapshot = {
    // Normalized address to the address as the user stored it.
    verifiedEmails: ReadonlyMap<string, string>
    unverifiedEmails: ReadonlySet<string>
    expiresAt: number
}

export type BlockedRecipient = { readonly address: string; readonly unverifiedMember: boolean }

// `deliverTo` holds the stored address of each allowed recipient, in the order the recipients came in.
export type RecipientCheck = { readonly blocked: BlockedRecipient[]; readonly deliverTo: string[] }

const MAX_SNAPSHOT_AGE_MS = 60_000
const REFRESH_AGE_MS = MAX_SNAPSHOT_AGE_MS - 1_000
// The lookup is one indexed join. A stalled one fails the check here instead of holding up every other
// send in the worker's batch, which waits for this invocation to finish. The deadline counts the wait for
// a pooled connection too; the statement timeout also stops the query on the server.
const LOOKUP_TIMEOUT_MS = 3_000
// A lookup past its deadline still waits in the common pool until it gets a connection, so at most this many
// are open at once. A check waiting for a slot holds nothing and fails at its deadline.
const MAX_OPEN_LOOKUPS = 5

type MemberRow = { team_id: number; email: string; is_email_verified: boolean }

const normalizeEmail = (email: string): string => email.trim().toLowerCase()

export class OrganizationMembersService {
    private snapshots: LazyLoader<OrganizationMemberSnapshot>
    private lookupSlots = new DeadlineSlots(MAX_OPEN_LOOKUPS)

    constructor(
        private postgres: PostgresRouter,
        private now: () => number = Date.now
    ) {
        this.snapshots = new LazyLoader({
            name: 'sandbox_team_organization_members',
            refreshAgeMs: REFRESH_AGE_MS,
            refreshJitterMs: 0,
            bufferMs: 0,
            loader: (teamIds) => this.loadSnapshots(teamIds),
        })
    }

    // `fresh` runs its own lookup, for the check right before delivery: a member removed while the
    // send was prepared must not receive it, so neither the cached snapshot nor a lookup another
    // send started earlier may answer it.
    // The match ignores case, so delivery goes to the stored address rather than the supplied one.
    public async checkRecipients(
        teamId: number,
        recipients: string[],
        { fresh = false }: { fresh?: boolean } = {}
    ): Promise<RecipientCheck> {
        const snapshot = fresh
            ? await this.loadOwnSnapshot(String(teamId))
            : await this.getFreshSnapshot(String(teamId))
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
        return { blocked, deliverTo }
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
        const rows = await this.lookupMembers(teamIds.map(Number))
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
                { verifiedEmails: verified, unverifiedEmails: unverified, expiresAt },
            ])
        )
    }

    private async lookupMembers(teamIds: number[]): Promise<MemberRow[]> {
        const tag = 'fetch-sandbox-team-organization-members'
        let timedOut = false
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<void>((resolve) => {
            timer = setTimeout(() => {
                timedOut = true
                resolve()
            }, LOOKUP_TIMEOUT_MS)
        })
        let rows: MemberRow[] | undefined
        const lookup = this.lookupSlots.run(deadline, async () => {
            rows = await this.postgres.transaction(PostgresUse.COMMON_WRITE, tag, async (tx) => {
                // Nobody waits for a lookup that got its connection after its deadline, so it runs no query.
                if (timedOut) {
                    throw new Error('The organization member lookup was abandoned at its deadline')
                }
                await this.postgres.query(tx, `SET LOCAL statement_timeout = ${LOOKUP_TIMEOUT_MS}`, undefined, tag)
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
                    [teamIds],
                    tag
                )
                return result.rows
            })
        })
        // A lookup that loses the race can still fail later, after nobody waits for it.
        lookup.catch(() => undefined)
        try {
            await Promise.race([lookup, deadline])
        } finally {
            clearTimeout(timer)
        }
        if (!rows) {
            throw new Error('The organization member lookup timed out')
        }
        return rows
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
