import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { EncryptedFields } from '../../utils/encryption-utils'

export type PushSubscriptionGetArgs = {
    teamId: number
    distinctId: string
    platform?: 'android' | 'ios' | 'web'
}

const toKey = (args: PushSubscriptionGetArgs): string => {
    return `${args.teamId}:${args.distinctId}:${args.platform ?? 'all'}`
}

const fromKey = (key: string): PushSubscriptionGetArgs => {
    const [teamId, distinctId, platform] = key.split(':', 3)
    return {
        teamId: parseInt(teamId),
        distinctId,
        platform: platform === 'all' ? undefined : (platform as 'android' | 'ios' | 'web'),
    }
}

// Type for the query result from the database
type PushSubscriptionRow = {
    id: string
    team_id: number
    distinct_id: string
    token: string
    platform: 'android' | 'ios' | 'web'
    is_active: boolean
    last_used_at: string | null
    created_at: string
    updated_at: string
}

export type PushSubscription = {
    id: string
    team_id: number
    distinct_id: string
    token: string
    platform: 'android' | 'ios' | 'web'
    is_active: boolean
    last_used_at: string | null
    created_at: string
    updated_at: string
}

export class PushSubscriptionsManagerService {
    private lazyLoader: LazyLoader<PushSubscription[]>

    constructor(
        private postgres: PostgresRouter,
        private encryptedFields: EncryptedFields
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'push_subscriptions_manager',
            loader: async (ids) => await this.fetchPushSubscriptions(ids),
        })
    }

    public clear(): void {
        this.lazyLoader.clear()
    }

    public async get(args: PushSubscriptionGetArgs): Promise<PushSubscription[]> {
        const key = toKey(args)
        return (await this.lazyLoader.get(key)) ?? []
    }

    public async getMany(args: PushSubscriptionGetArgs[]): Promise<Record<string, PushSubscription[]>> {
        const keys = args.map(toKey)
        return await this.lazyLoader.getMany(keys)
    }

    private async fetchPushSubscriptions(ids: string[]): Promise<Record<string, PushSubscription[] | undefined>> {
        const subscriptionArgs = ids.map(fromKey)

        logger.debug('[PushSubscriptionsManager]', 'Fetching push subscriptions', { subscriptionArgs })

        // Separate queries with and without platform filter for efficiency
        const withPlatform: Array<{ index: number; args: PushSubscriptionGetArgs }> = []
        const withoutPlatform: Array<{ index: number; args: PushSubscriptionGetArgs }> = []

        subscriptionArgs.forEach((args, index) => {
            if (args.platform) {
                withPlatform.push({ index, args })
            } else {
                withoutPlatform.push({ index, args })
            }
        })

        const allResults: PushSubscriptionRow[] = []

        // Query subscriptions with platform filter
        if (withPlatform.length > 0) {
            const conditions = withPlatform
                .map((_, idx) => {
                    const baseIdx = idx * 3
                    return `(team_id = $${baseIdx + 1} AND distinct_id = $${baseIdx + 2} AND platform = $${baseIdx + 3} AND is_active = true)`
                })
                .join(' OR ')

            const params = withPlatform.flatMap((item) => [item.args.teamId, item.args.distinctId, item.args.platform!])

            const queryString = `SELECT
                    id,
                    team_id,
                    distinct_id,
                    token,
                    platform,
                    is_active,
                    last_used_at,
                    created_at,
                    updated_at
                FROM workflows_pushsubscription
                WHERE ${conditions}
                ORDER BY last_used_at DESC NULLS LAST, created_at DESC`

            const response = await this.postgres.query<PushSubscriptionRow>(
                PostgresUse.COMMON_READ,
                queryString,
                params,
                'fetchPushSubscriptionsWithPlatform'
            )

            allResults.push(...response.rows)
        }

        // Query subscriptions without platform filter
        if (withoutPlatform.length > 0) {
            const conditions = withoutPlatform
                .map((_, idx) => {
                    const baseIdx = idx * 2
                    return `(team_id = $${baseIdx + 1} AND distinct_id = $${baseIdx + 2} AND is_active = true)`
                })
                .join(' OR ')

            const params = withoutPlatform.flatMap((item) => [item.args.teamId, item.args.distinctId])

            const queryString = `SELECT
                    id,
                    team_id,
                    distinct_id,
                    token,
                    platform,
                    is_active,
                    last_used_at,
                    created_at,
                    updated_at
                FROM workflows_pushsubscription
                WHERE ${conditions}
                ORDER BY last_used_at DESC NULLS LAST, created_at DESC`

            const response = await this.postgres.query<PushSubscriptionRow>(
                PostgresUse.COMMON_READ,
                queryString,
                params,
                'fetchPushSubscriptionsWithoutPlatform'
            )

            allResults.push(...response.rows)
        }

        const subscriptionRows = allResults

        // Group results by key
        const result: Record<string, PushSubscription[]> = {}

        // Initialize all keys with empty arrays
        for (const key of ids) {
            result[key] = []
        }

        for (const row of subscriptionRows) {
            // Find matching keys (could match multiple if platform was not specified)
            for (const key of ids) {
                const args = fromKey(key)
                if (
                    args.teamId === row.team_id &&
                    args.distinctId === row.distinct_id &&
                    (!args.platform || args.platform === row.platform)
                ) {
                    const decryptedToken =
                        this.encryptedFields.decrypt(row.token, { ignoreDecryptionErrors: true }) ?? row.token
                    result[key].push({
                        id: row.id,
                        team_id: row.team_id,
                        distinct_id: row.distinct_id,
                        token: decryptedToken,
                        platform: row.platform,
                        is_active: row.is_active,
                        last_used_at: row.last_used_at,
                        created_at: row.created_at,
                        updated_at: row.updated_at,
                    })
                }
            }
        }

        return result
    }
}
