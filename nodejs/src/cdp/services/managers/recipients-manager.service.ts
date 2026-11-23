import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { isValidTeamId } from '~/common/utils/team-manager'

export type RecipientGetArgs = {
    teamId: number
    identifier: string
    /** The identifier is an email address, which matches a preference stored in any case. Push distinct IDs and
     * phone numbers leave this off, because they are case-sensitive even when they contain `@`. */
    anyCase?: boolean
}

const toKey = (args: RecipientGetArgs): string => `${args.teamId}:${args.identifier}`

const fromKey = (key: string): RecipientGetArgs => {
    const [teamId, identifier] = key.split(':', 2)
    return { teamId: Number(teamId), identifier }
}

export type PreferenceStatus = 'OPTED_IN' | 'OPTED_OUT' | 'NO_PREFERENCE'

// Reserved key in the preferences JSON for open/click tracking consent, alongside the '$all'
// unsubscribe key. Mirrors EMAIL_TRACKING_PREFERENCE_ID in
// products/messaging/backend/models/message_preferences.py.
export const EMAIL_TRACKING_PREFERENCE_ID = '$email_tracking'

// Type for the query result from the database
type MessageRecipientPreferenceRow = {
    id: string
    team_id: number
    identifier: string
    preferences: Record<string, string>
    created_at: string
    updated_at: string
    deleted: boolean
}

export type RecipientManagerRecipient = {
    id: string
    team_id: number
    identifier: string
    preferences: Record<string, PreferenceStatus>
    created_at: string
    updated_at: string
}

const FRESH_BATCH_SIZE = 500

type PendingFreshRequest = {
    key: string
    resolve: (recipient: RecipientManagerRecipient | null) => void
    reject: (error: unknown) => void
}

export class RecipientsManagerService {
    private lazyLoader: LazyLoader<RecipientManagerRecipient>
    private anyCaseLoader: LazyLoader<RecipientManagerRecipient>
    private pendingFresh: Record<'exact' | 'anyCase', PendingFreshRequest[] | null> = {
        exact: null,
        anyCase: null,
    }

    constructor(private postgres: Pick<PostgresRouter, 'query'>) {
        this.lazyLoader = new LazyLoader({
            name: 'recipients_manager',
            loader: async (ids) => await this.fetchRecipients(ids, false),
        })
        this.anyCaseLoader = new LazyLoader({
            name: 'recipients_manager_any_case',
            loader: async (ids) => await this.fetchRecipients(ids, true),
        })
    }

    public clear(): void {
        this.lazyLoader.clear()
        this.anyCaseLoader.clear()
    }

    public async get(args: RecipientGetArgs): Promise<RecipientManagerRecipient | null> {
        const key = toKey(args)
        return (await (args.anyCase ? this.anyCaseLoader : this.lazyLoader).get(key)) ?? null
    }

    /** Reads directly from the primary database without consulting or populating the cache,
     * batching concurrent callers that arrive before a query starts. */
    public getFresh(args: RecipientGetArgs): Promise<RecipientManagerRecipient | null> {
        const anyCase = Boolean(args.anyCase)
        const bucket = anyCase ? 'anyCase' : 'exact'
        const key = toKey(args)
        return new Promise((resolve, reject) => {
            let queue = this.pendingFresh[bucket]
            if (!queue) {
                queue = []
                this.pendingFresh[bucket] = queue
                queueMicrotask(() => {
                    void this.flushFresh(bucket, anyCase)
                })
            }
            queue.push({ key, resolve, reject })
        })
    }

    private async flushFresh(bucket: 'exact' | 'anyCase', anyCase: boolean): Promise<void> {
        const batch = this.pendingFresh[bucket]
        this.pendingFresh[bucket] = null
        if (!batch?.length) {
            return
        }
        const uniqueKeys = [...new Set(batch.map((entry) => entry.key))]
        try {
            const rows: Record<string, RecipientManagerRecipient | undefined> = Object.create(null)
            for (let i = 0; i < uniqueKeys.length; i += FRESH_BATCH_SIZE) {
                const chunk = await this.fetchRecipients(
                    uniqueKeys.slice(i, i + FRESH_BATCH_SIZE),
                    anyCase,
                    PostgresUse.COMMON_WRITE
                )
                Object.assign(rows, chunk)
            }
            for (const entry of batch) {
                entry.resolve(rows[entry.key] ?? null)
            }
        } catch (error) {
            for (const entry of batch) {
                entry.reject(error)
            }
        }
    }

    public async getMany(args: RecipientGetArgs[]): Promise<Record<string, RecipientManagerRecipient | null>> {
        const exact = await this.lazyLoader.getMany(args.filter((a) => !a.anyCase).map(toKey))
        const anyCase = await this.anyCaseLoader.getMany(args.filter((a) => a.anyCase).map(toKey))
        return { ...exact, ...anyCase }
    }

    /**
     * Get preference status for a specific category
     */
    public getPreference(recipient: RecipientManagerRecipient, categoryId: string): PreferenceStatus {
        return recipient.preferences[categoryId] ?? 'NO_PREFERENCE'
    }

    public getAllMarketingMessagingPreference(recipient: RecipientManagerRecipient): PreferenceStatus {
        return recipient.preferences['$all'] ?? 'NO_PREFERENCE'
    }

    // Consent for open/click tracking, distinct from messaging opt-out: a recipient can keep
    // receiving emails while refusing to have their opens/clicks tracked.
    public getEmailTrackingPreference(recipient: RecipientManagerRecipient): PreferenceStatus {
        return recipient.preferences[EMAIL_TRACKING_PREFERENCE_ID] ?? 'NO_PREFERENCE'
    }

    /**
     * Opt out one or more recipients from all marketing messaging by upserting the $all preference to OPTED_OUT.
     */
    public async optOut(teamId: number, identifiers: string[]): Promise<void> {
        if (identifiers.length === 0) {
            return
        }

        const preferences = JSON.stringify({ $all: 'OPTED_OUT' })

        // Build a single INSERT with multiple VALUES rows
        const valueClauses: string[] = []
        const params: (number | string)[] = []
        for (let i = 0; i < identifiers.length; i++) {
            const teamParam = i * 3 + 1
            const identifierParam = i * 3 + 2
            const prefsParam = i * 3 + 3
            valueClauses.push(
                `(gen_random_uuid(), $${teamParam}, $${identifierParam}, $${prefsParam}, NOW(), NOW(), false)`
            )
            params.push(teamId, identifiers[i], preferences)
        }

        const queryString = `
            INSERT INTO posthog_messagerecipientpreference (id, team_id, identifier, preferences, created_at, updated_at, deleted)
            VALUES ${valueClauses.join(', ')}
            ON CONFLICT (team_id, identifier)
            DO UPDATE SET
                preferences = posthog_messagerecipientpreference.preferences || EXCLUDED.preferences,
                updated_at = NOW()
        `

        await this.postgres.query(PostgresUse.COMMON_WRITE, queryString, params, 'optOutRecipients')

        // Clear the cache so subsequent reads pick up the new preferences
        this.clear()
    }

    private async fetchRecipients(
        ids: string[],
        anyCase: boolean,
        postgresUse: PostgresUse = PostgresUse.COMMON_READ
    ): Promise<Record<string, RecipientManagerRecipient | undefined>> {
        const recipientArgs = ids.map(fromKey).filter(({ teamId }) => isValidTeamId(teamId))
        if (recipientArgs.length === 0) {
            return {}
        }

        logger.debug('[RecipientsManager]', 'Fetching recipients', { recipientArgs })

        // An email address matches whatever case it was stored in, so an opt-out saved as `User@Example.com` also
        // stops a send to `user@example.com`. Other identifiers, such as a push distinct ID, match exactly.
        const matchKey = (teamId: number, identifier: string): string =>
            toKey({ teamId, identifier: anyCase ? identifier.toLowerCase() : identifier })
        const conditions = recipientArgs
            .map((_, index) => {
                const teamIdParam = index * 2 + 1
                const identifierParam = index * 2 + 2
                return anyCase
                    ? `(team_id = $${teamIdParam} AND lower(identifier) = lower($${identifierParam}))`
                    : `(team_id = $${teamIdParam} AND identifier = $${identifierParam})`
            })
            .join(' OR ')

        const queryString = `SELECT
                id,
                team_id,
                identifier,
                preferences,
                created_at,
                updated_at,
                deleted
            FROM posthog_messagerecipientpreference
            WHERE ${conditions} AND deleted = false`

        // Flatten the parameters: [teamId1, identifier1, teamId2, identifier2, ...]
        const params = recipientArgs.flatMap((recipient) => [recipient.teamId, recipient.identifier])

        const response = await this.postgres.query<MessageRecipientPreferenceRow>(
            postgresUse,
            queryString,
            params,
            'fetchCDPRecipients'
        )

        const rowsByAddress = new Map<string, MessageRecipientPreferenceRow[]>()
        for (const row of response.rows) {
            const key = matchKey(row.team_id, row.identifier)
            const rows = rowsByAddress.get(key)
            if (rows) {
                rows.push(row)
            } else {
                rowsByAddress.set(key, [row])
            }
        }

        const result: Record<string, RecipientManagerRecipient | undefined> = {}
        for (const args of recipientArgs) {
            const rows = rowsByAddress.get(matchKey(args.teamId, args.identifier))
            if (!rows?.length) {
                continue
            }
            // The spelling the send names wins. Between other spellings, the latest change wins.
            const ordered = [...rows].sort(
                (a, b) =>
                    Number(a.identifier === args.identifier) - Number(b.identifier === args.identifier) ||
                    String(a.updated_at).localeCompare(String(b.updated_at))
            )
            const chosen = ordered[ordered.length - 1]
            const merged: Record<string, string> = Object.assign({}, ...ordered.map((row) => row.preferences))

            // Convert raw preferences object to typed preferences
            const typedPreferences: Record<string, PreferenceStatus> = {}
            for (const [categoryId, status] of Object.entries(merged)) {
                if (['OPTED_IN', 'OPTED_OUT', 'NO_PREFERENCE'].includes(status)) {
                    typedPreferences[categoryId] = status as PreferenceStatus
                } else {
                    typedPreferences[categoryId] = 'NO_PREFERENCE'
                }
            }

            result[toKey(args)] = {
                id: chosen.id,
                team_id: chosen.team_id,
                identifier: chosen.identifier,
                preferences: typedPreferences,
                created_at: chosen.created_at,
                updated_at: chosen.updated_at,
            }
        }

        return result
    }
}
