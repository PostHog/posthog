import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'

export type RecipientGetArgs = {
    teamId: number
    identifier: string
}

const toKey = (args: RecipientGetArgs): string => `${args.teamId}:${args.identifier}`

const fromKey = (key: string): RecipientGetArgs => {
    const [teamId, identifier] = key.split(':', 2)
    return { teamId: parseInt(teamId), identifier }
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

// Longer than the cache keeps an entry (5 minutes plus up to 1 minute of jitter). A lookup that was in flight when the
// recipient changed can cache the old preferences, so lookups bypass the cache until that entry has expired.
const PRIMARY_READ_WINDOW_MS = 7 * 60 * 1000

export class RecipientsManagerService {
    private lazyLoader: LazyLoader<RecipientManagerRecipient>
    private primaryReadsUntil = new Map<string, number>()

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'recipients_manager',
            loader: async (ids) => await this.fetchRecipients(ids),
        })
    }

    public clear(): void {
        this.lazyLoader.clear()
        this.primaryReadsUntil.clear()
    }

    /**
     * Read this recipient from the primary database, bypassing the cache, right after their preferences change.
     * A replica can lag behind that write, and a cached or in-flight lookup can hold the old preferences.
     */
    public markForRefresh(args: RecipientGetArgs): void {
        const key = toKey(args)
        this.pruneExpiredPrimaryReads()
        // Re-inserting moves the key to the end, so the map stays in expiry order.
        this.primaryReadsUntil.delete(key)
        this.primaryReadsUntil.set(key, Date.now() + PRIMARY_READ_WINDOW_MS)
        this.lazyLoader.markForRefresh(key)
    }

    private pruneExpiredPrimaryReads(): void {
        const now = Date.now()
        for (const [key, until] of this.primaryReadsUntil) {
            if (until > now) {
                return
            }
            this.primaryReadsUntil.delete(key)
        }
    }

    private readsFromPrimary(key: string): boolean {
        return (this.primaryReadsUntil.get(key) ?? 0) > Date.now()
    }

    public async get(args: RecipientGetArgs): Promise<RecipientManagerRecipient | null> {
        return (await this.getMany([args]))[toKey(args)] ?? null
    }

    public async getMany(args: RecipientGetArgs[]): Promise<Record<string, RecipientManagerRecipient | null>> {
        const keys = args.map(toKey)
        const primaryKeys = keys.filter((key) => this.readsFromPrimary(key))
        if (primaryKeys.length === 0) {
            return await this.lazyLoader.getMany(keys)
        }
        const cachedKeys = keys.filter((key) => !this.readsFromPrimary(key))
        const [cached, primary] = await Promise.all([
            cachedKeys.length > 0 ? this.lazyLoader.getMany(cachedKeys) : Promise.resolve({}),
            this.fetchRecipients(primaryKeys, PostgresUse.COMMON_WRITE),
        ])
        const results: Record<string, RecipientManagerRecipient | null> = { ...cached }
        for (const key of primaryKeys) {
            results[key] = primary[key] ?? null
        }
        return results
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
        this.lazyLoader.clear()
    }

    private async fetchRecipients(
        ids: string[],
        use: PostgresUse = PostgresUse.COMMON_READ
    ): Promise<Record<string, RecipientManagerRecipient | undefined>> {
        const recipientArgs = ids.map(fromKey)

        logger.debug('[RecipientsManager]', 'Fetching recipients', { recipientArgs })

        // Build the WHERE clause for multiple team_id, identifier pairs
        const conditions = recipientArgs
            .map((_, index) => {
                const teamIdParam = index * 2 + 1
                const identifierParam = index * 2 + 2
                // NOTE: We have a unique index on (team_id, identifier) so this should be efficient
                return `(team_id = $${teamIdParam} AND identifier = $${identifierParam})`
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
            use,
            queryString,
            params,
            'fetchCDPRecipients'
        )

        const recipientRows = response.rows

        // Map results back to the original keys
        const result: Record<string, RecipientManagerRecipient | undefined> = {}

        for (const row of recipientRows) {
            const key = toKey({ teamId: row.team_id, identifier: row.identifier })

            // Convert raw preferences object to typed preferences
            const typedPreferences: Record<string, PreferenceStatus> = {}
            for (const [categoryId, status] of Object.entries(row.preferences)) {
                if (['OPTED_IN', 'OPTED_OUT', 'NO_PREFERENCE'].includes(status)) {
                    typedPreferences[categoryId] = status as PreferenceStatus
                } else {
                    typedPreferences[categoryId] = 'NO_PREFERENCE'
                }
            }

            result[key] = {
                id: row.id,
                team_id: row.team_id,
                identifier: row.identifier,
                preferences: typedPreferences,
                created_at: row.created_at,
                updated_at: row.updated_at,
            }
        }

        return result
    }
}
