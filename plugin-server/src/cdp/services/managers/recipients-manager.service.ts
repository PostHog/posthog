import { Hub } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'

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

    constructor(private hub: Hub) {
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

    private async fetchRecipients(ids: string[]): Promise<Record<string, RecipientManagerRecipient | undefined>> {
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

        const response = await this.hub.postgres.query<MessageRecipientPreferenceRow>(
            PostgresUse.COMMON_READ,
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
