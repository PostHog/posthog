import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { isValidTeamId } from '~/common/utils/team-manager'

export type RecipientGetArgs = {
    teamId: number
    identifier: string
}

const toKey = (args: RecipientGetArgs): string => `${args.teamId}:${args.identifier}`

const fromKey = (key: string): RecipientGetArgs => {
    const [teamId, identifier] = key.split(':', 2)
    return { teamId: Number(teamId), identifier }
}

const isEmail = (identifier: string): boolean => identifier.includes('@')

// Rows for one address in any case share this key.
const matchKey = (identifier: string): string => (isEmail(identifier) ? identifier.toLowerCase() : identifier)

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

export class RecipientsManagerService {
    private lazyLoader: LazyLoader<RecipientManagerRecipient>

    constructor(private postgres: Pick<PostgresRouter, 'query'>) {
        this.lazyLoader = new LazyLoader({
            name: 'recipients_manager',
            loader: async (ids) => await this.fetchRecipients(ids),
        })
    }

    public clear(): void {
        this.lazyLoader.clear()
    }

    public async get(args: RecipientGetArgs): Promise<RecipientManagerRecipient | null> {
        const key = toKey(args)
        return (await this.lazyLoader.get(key)) ?? null
    }

    public async getMany(args: RecipientGetArgs[]): Promise<Record<string, RecipientManagerRecipient | null>> {
        const keys = args.map(toKey)
        return await this.lazyLoader.getMany(keys)
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

    private async fetchRecipients(ids: string[]): Promise<Record<string, RecipientManagerRecipient | undefined>> {
        const recipientArgs = ids.map(fromKey).filter(({ teamId }) => isValidTeamId(teamId))
        if (recipientArgs.length === 0) {
            return {}
        }

        logger.debug('[RecipientsManager]', 'Fetching recipients', { recipientArgs })

        // An email address matches whatever case it was stored in, so an opt-out saved as `User@Example.com` also
        // stops a send to `user@example.com`. Other identifiers, such as a push distinct ID, match exactly.
        const conditions = recipientArgs
            .map(({ identifier }, index) => {
                const teamIdParam = index * 2 + 1
                const identifierParam = index * 2 + 2
                return isEmail(identifier)
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
            PostgresUse.COMMON_READ,
            queryString,
            params,
            'fetchCDPRecipients'
        )

        const rowsByAddress = new Map<string, MessageRecipientPreferenceRow[]>()
        for (const row of response.rows) {
            const key = toKey({ teamId: row.team_id, identifier: matchKey(row.identifier) })
            rowsByAddress.set(key, [...(rowsByAddress.get(key) ?? []), row])
        }

        const result: Record<string, RecipientManagerRecipient | undefined> = {}
        for (const args of recipientArgs) {
            const rows = rowsByAddress.get(toKey({ teamId: args.teamId, identifier: matchKey(args.identifier) }))
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
