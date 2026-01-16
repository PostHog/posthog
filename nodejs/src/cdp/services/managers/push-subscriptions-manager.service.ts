import { createHash } from 'crypto'

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
    last_successfully_used_at: string | null
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
    last_successfully_used_at: string | null
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

    public async getMany(args: PushSubscriptionGetArgs[]): Promise<Record<string, PushSubscription[] | null>> {
        const keys = args.map(toKey)
        return await this.lazyLoader.getMany(keys)
    }

    public async getById(teamId: number, subscriptionId: string): Promise<PushSubscription | null> {
        const queryString = `SELECT
                id,
                team_id,
                distinct_id,
                token,
                platform,
                is_active,
                last_successfully_used_at,
                created_at,
                updated_at
            FROM workflows_pushsubscription
            WHERE id = $1 AND team_id = $2 AND is_active = true
            LIMIT 1`

        const rows = (
            await this.postgres.query<PushSubscriptionRow>(
                PostgresUse.COMMON_READ,
                queryString,
                [subscriptionId, teamId],
                'getPushSubscriptionById'
            )
        ).rows

        const row = rows[0] ?? null
        if (!row) {
            return null
        }

        const decryptedToken = this.encryptedFields.decrypt(row.token, { ignoreDecryptionErrors: true }) ?? row.token

        return {
            id: row.id,
            team_id: row.team_id,
            distinct_id: row.distinct_id,
            token: decryptedToken,
            platform: row.platform,
            is_active: row.is_active,
            last_successfully_used_at: row.last_successfully_used_at,
            created_at: row.created_at,
            updated_at: row.updated_at,
        }
    }

    private async fetchPushSubscriptions(ids: string[]): Promise<Record<string, PushSubscription[] | undefined>> {
        const subscriptionArgs = ids.map(fromKey)

        logger.debug('[PushSubscriptionsManager]', 'Fetching push subscriptions', { subscriptionArgs })

        // Separate queries with and without platform filter for efficiency
        const withPlatformFilter: Array<{ index: number; args: PushSubscriptionGetArgs }> = []
        const withoutPlatformFilter: Array<{ index: number; args: PushSubscriptionGetArgs }> = []

        subscriptionArgs.forEach((args, index) => {
            if (args.platform) {
                withPlatformFilter.push({ index, args })
            } else {
                withoutPlatformFilter.push({ index, args })
            }
        })

        const allResults: PushSubscriptionRow[] = []

        // Query subscriptions with platform filter
        if (withPlatformFilter.length > 0) {
            const conditions = withPlatformFilter
                .map((_, idx) => {
                    const baseIdx = idx * 3
                    return `(team_id = $${baseIdx + 1} AND distinct_id = $${baseIdx + 2} AND platform = $${baseIdx + 3} AND is_active = true)`
                })
                .join(' OR ')

            const params = withPlatformFilter.flatMap((item) => [
                item.args.teamId,
                item.args.distinctId,
                item.args.platform!,
            ])

            const queryString = `SELECT
                    id,
                    team_id,
                    distinct_id,
                    token,
                    platform,
                    is_active,
                    last_successfully_used_at,
                    created_at,
                    updated_at
                FROM workflows_pushsubscription
                WHERE ${conditions}
                ORDER BY last_successfully_used_at DESC NULLS LAST, created_at DESC`

            const response = await this.postgres.query<PushSubscriptionRow>(
                PostgresUse.COMMON_READ,
                queryString,
                params,
                'fetchPushSubscriptionsWithPlatform'
            )

            allResults.push(...response.rows)
        }

        // Query subscriptions without platform filter
        if (withoutPlatformFilter.length > 0) {
            const conditions = withoutPlatformFilter
                .map((_, idx) => {
                    const baseIdx = idx * 2
                    return `(team_id = $${baseIdx + 1} AND distinct_id = $${baseIdx + 2} AND is_active = true)`
                })
                .join(' OR ')

            const params = withoutPlatformFilter.flatMap((item) => [item.args.teamId, item.args.distinctId])

            const queryString = `SELECT
                    id,
                    team_id,
                    distinct_id,
                    token,
                    platform,
                    is_active,
                    last_successfully_used_at,
                    created_at,
                    updated_at
                FROM workflows_pushsubscription
                WHERE ${conditions}
                ORDER BY last_successfully_used_at DESC NULLS LAST, created_at DESC`

            const response = await this.postgres.query<PushSubscription>(
                PostgresUse.COMMON_READ,
                queryString,
                params,
                'fetchPushSubscriptionsWithoutPlatform'
            )

            allResults.push(...response.rows)
        }

        // Deduplicate results by id (same subscription could appear in both queries)
        const uniqueRows = new Map<string, PushSubscriptionRow>()
        for (const row of allResults) {
            if (!uniqueRows.has(row.id)) {
                uniqueRows.set(row.id, row)
            }
        }

        const subscriptionRows = Array.from(uniqueRows.values())

        // Group results by key
        const result: Record<string, PushSubscription[]> = {}

        for (const key of ids) {
            result[key] = []
        }

        for (const row of subscriptionRows) {
            // Find matching keys (could match multiple)
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
                        last_successfully_used_at: row.last_successfully_used_at,
                        created_at: row.created_at,
                        updated_at: row.updated_at,
                    })
                }
            }
        }

        return result
    }

    public async updateLastSuccessfullyUsedAt(subscriptionIds: string[]): Promise<void> {
        if (subscriptionIds.length === 0) {
            return
        }

        const placeholders = subscriptionIds.map((_, idx) => `$${idx + 1}`).join(', ')
        const queryString = `UPDATE workflows_pushsubscription
            SET last_successfully_used_at = NOW()
            WHERE id IN (${placeholders})`

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            queryString,
            subscriptionIds,
            'updatePushSubscriptionLastSuccessfullyUsedAt'
        )
    }

    public async updateLastSuccessfullyUsedAtByToken(teamId: number, token: string): Promise<void> {
        const tokenHash = this.hashToken(token)
        const queryString = `UPDATE workflows_pushsubscription
            SET last_successfully_used_at = NOW()
            WHERE team_id = $1 AND token_hash = $2 AND is_active = true`

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            queryString,
            [teamId, tokenHash],
            'updatePushSubscriptionLastSuccessfullyUsedAtByToken'
        )
    }

    public async deactivateToken(teamId: number, token: string, reason: string): Promise<void> {
        const tokenHash = this.hashToken(token)
        const queryString = `UPDATE workflows_pushsubscription
            SET is_active = false, disabled_reason = $1
            WHERE team_id = $2 AND token_hash = $3 AND is_active = true`

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            queryString,
            [reason, teamId, tokenHash],
            'deactivatePushSubscriptionToken'
        )
    }

    private hashToken(token: string): string {
        return createHash('sha256').update(token, 'utf-8').digest('hex')
    }
}
