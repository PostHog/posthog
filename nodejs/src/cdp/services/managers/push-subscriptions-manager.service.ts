import { createHash } from 'crypto'
import { Counter } from 'prom-client'

import { parseJSON } from '~/utils/json-parse'

import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { HogFunctionType } from '../../types'
import { EncryptedFields } from '../../utils/encryption-utils'

export type FcmErrorDetail = { '@type'?: string; errorCode?: string }

export type PushSubscriptionGetArgs = {
    teamId: number
    distinctId: string
    platform?: 'android' | 'ios'
    firebaseAppId?: string
    provider?: 'fcm' | 'apns'
}

const toKey = (args: PushSubscriptionGetArgs): string => {
    // Use JSON encoding to safely handle distinctIds containing colons or other special characters
    return JSON.stringify([
        args.teamId,
        args.distinctId,
        args.platform ?? 'all',
        args.firebaseAppId ?? 'all',
        args.provider ?? 'all',
    ])
}

const getDistinctIdsForSamePersonCounter = new Counter({
    name: 'cdp_push_subscription_get_distinct_ids_for_same_person_total',
    help: 'Total number of getDistinctIdsForSamePerson calls',
})

const fromKey = (key: string): PushSubscriptionGetArgs => {
    // Parse JSON-encoded key to safely handle distinctIds containing colons or other special characters
    const [teamId, distinctId, platform, firebaseAppId, provider] = parseJSON(key)
    return {
        teamId: parseInt(teamId),
        distinctId,
        platform: platform === 'all' ? undefined : (platform as 'android' | 'ios'),
        firebaseAppId: firebaseAppId === 'all' ? undefined : firebaseAppId,
        provider: provider === 'all' ? undefined : (provider as 'fcm' | 'apns'),
    }
}

// Type for the query result from the database
type PushSubscriptionRow = {
    id: string
    team_id: number
    distinct_id: string
    token: string
    platform: 'android' | 'ios'
    provider: 'fcm' | 'apns'
    is_active: boolean
    last_successfully_used_at: string | null
    created_at: string
    updated_at: string
    firebase_app_id: string | null
}

export type PushSubscription = {
    id: string
    team_id: number
    distinct_id: string
    token: string
    platform: 'android' | 'ios'
    provider: 'fcm' | 'apns'
    is_active: boolean
    last_successfully_used_at: string | null
    created_at: string
    updated_at: string
}

export type PushSubscriptionInputToLoad = {
    distinctId: string
    firebaseAppId: string
    platform?: 'android' | 'ios'
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
                provider,
                is_active,
                last_successfully_used_at,
                created_at,
                updated_at,
                firebase_app_id
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
            provider: row.provider,
            is_active: row.is_active,
            last_successfully_used_at: row.last_successfully_used_at,
            created_at: row.created_at,
            updated_at: row.updated_at,
        }
    }

    private async fetchPushSubscriptions(ids: string[]): Promise<Record<string, PushSubscription[] | undefined>> {
        const subscriptionArgs = ids.map(fromKey)

        // Separate queries by platform, provider, and firebase_app_id filters for efficiency
        const queryGroups: Array<{ indices: number[]; args: PushSubscriptionGetArgs[] }> = []
        const grouped = new Map<string, number[]>()

        subscriptionArgs.forEach((args, index) => {
            const groupKey = JSON.stringify({
                platform: args.platform ?? 'all',
                provider: args.provider ?? 'all',
                firebaseAppId: args.firebaseAppId ?? 'all',
            })
            if (!grouped.has(groupKey)) {
                grouped.set(groupKey, [])
            }
            grouped.get(groupKey)!.push(index)
        })

        grouped.forEach((indices) => {
            const args = indices.map((idx) => subscriptionArgs[idx])
            queryGroups.push({ indices, args })
        })

        const allResults: PushSubscriptionRow[] = []

        // Execute queries for each group
        for (const group of queryGroups) {
            const conditions: string[] = []
            const params: any[] = []
            let paramIdx = 1

            for (const args of group.args) {
                const conditionParts: string[] = [`team_id = $${paramIdx++}`, `distinct_id = $${paramIdx++}`]
                params.push(args.teamId, args.distinctId)

                if (args.platform) {
                    conditionParts.push(`platform = $${paramIdx++}`)
                    params.push(args.platform)
                }

                if (args.provider) {
                    conditionParts.push(`provider = $${paramIdx++}`)
                    params.push(args.provider)
                }

                if (args.firebaseAppId) {
                    conditionParts.push(`(firebase_app_id = $${paramIdx++} OR firebase_app_id IS NULL)`)
                    params.push(args.firebaseAppId)
                }

                conditionParts.push('is_active = true')
                conditions.push(`(${conditionParts.join(' AND ')})`)
            }

            const queryString = `SELECT
                    id,
                    team_id,
                    distinct_id,
                    token,
                    platform,
                    provider,
                    is_active,
                    last_successfully_used_at,
                    created_at,
                    updated_at,
                    firebase_app_id
                FROM workflows_pushsubscription
                WHERE ${conditions.join(' OR ')}
                ORDER BY last_successfully_used_at DESC NULLS LAST, created_at DESC`

            const response = await this.postgres.query<PushSubscriptionRow>(
                PostgresUse.COMMON_READ,
                queryString,
                params,
                'fetchPushSubscriptions'
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
                const matchesPlatform = !args.platform || args.platform === row.platform
                const matchesProvider = !args.provider || args.provider === row.provider
                const matchesAppId =
                    !args.firebaseAppId || args.firebaseAppId === row.firebase_app_id || row.firebase_app_id === null

                if (
                    args.teamId === row.team_id &&
                    args.distinctId === row.distinct_id &&
                    matchesPlatform &&
                    matchesProvider &&
                    matchesAppId
                ) {
                    const decryptedToken =
                        this.encryptedFields.decrypt(row.token, { ignoreDecryptionErrors: true }) ?? row.token
                    result[key].push({
                        id: row.id,
                        team_id: row.team_id,
                        distinct_id: row.distinct_id,
                        token: decryptedToken,
                        platform: row.platform,
                        provider: row.provider,
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

    public async deactivateTokens(tokens: string[], reason: string, teamId: number): Promise<void> {
        if (tokens.length === 0) {
            return
        }
        const tokenHashes = tokens.map((token) => this.hashToken(token))
        const queryString = `UPDATE workflows_pushsubscription
            SET is_active = false, disabled_reason = $1
            WHERE team_id = $2 AND token_hash = ANY($3::text[]) AND is_active = true`

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            queryString,
            [reason, teamId, tokenHashes],
            'deactivatePushSubscriptionTokens'
        )
    }

    public async updateTokenLifecycle(
        teamId: number,
        fcmToken: string,
        status: number | undefined,
        errorDetails: FcmErrorDetail[] | undefined
    ): Promise<void> {
        if (status && status >= 200 && status < 300) {
            try {
                await this.updateLastSuccessfullyUsedAtByToken(teamId, fcmToken)
            } catch (error) {
                logger.warn('Failed to update last_successfully_used_at for FCM token', { teamId, error })
            }
            return
        }

        if (status === 404) {
            try {
                await this.deactivateTokens([fcmToken], 'unregistered token', teamId)
                logger.info('Deactivated push subscription token due to 404 (unregistered token)', { teamId })
            } catch (error) {
                logger.warn('Failed to deactivate push subscription token', { teamId, error })
            }
            return
        }

        if (status === 400 && errorDetails) {
            const isInvalidArgument = errorDetails.some(
                (d) =>
                    d['@type'] === 'type.googleapis.com/google.firebase.fcm.v1.FcmError' &&
                    d.errorCode === 'INVALID_ARGUMENT'
            )
            if (isInvalidArgument) {
                try {
                    await this.deactivateTokens([fcmToken], 'invalid token', teamId)
                    logger.info('Deactivated push subscription token due to 400 INVALID_ARGUMENT (invalid token)', {
                        teamId,
                    })
                } catch (error) {
                    logger.warn('Failed to deactivate push subscription token', { teamId, error })
                }
            }
        }
    }

    public async getDistinctIdsForSamePerson(teamId: number, distinctId: string): Promise<string[]> {
        getDistinctIdsForSamePersonCounter.inc()
        const queryString = `SELECT DISTINCT distinct_id
            FROM posthog_persondistinctid
            WHERE team_id = $1 
              AND person_id = (
                  SELECT person_id 
                  FROM posthog_persondistinctid 
                  WHERE team_id = $1 AND distinct_id = $2
                  LIMIT 1
              )`

        const { rows } = await this.postgres.query<{ distinct_id: string }>(
            PostgresUse.PERSONS_READ,
            queryString,
            [teamId, distinctId],
            'getDistinctIdsForSamePerson'
        )

        return rows.map((row) => row.distinct_id)
    }

    public async findSubscriptionByPersonDistinctIds(
        teamId: number,
        distinctIds: string[],
        platform?: 'android' | 'ios',
        firebaseAppId?: string,
        provider?: 'fcm' | 'apns'
    ): Promise<PushSubscription | null> {
        if (distinctIds.length === 0) {
            return null
        }

        const placeholders = distinctIds.map((_, idx) => `$${idx + 2}`).join(', ')
        let paramIndex = distinctIds.length + 2
        const platformFilter = platform ? `AND platform = $${paramIndex++}` : ''
        const providerFilter = provider ? `AND provider = $${paramIndex++}` : ''
        const appIdFilter = firebaseAppId ? `AND (firebase_app_id = $${paramIndex++} OR firebase_app_id IS NULL)` : ''

        const params: any[] = [teamId, ...distinctIds]
        if (platform) {
            params.push(platform)
        }
        if (provider) {
            params.push(provider)
        }
        if (firebaseAppId) {
            params.push(firebaseAppId)
        }

        const queryString = `SELECT
                id,
                team_id,
                distinct_id,
                token,
                platform,
                provider,
                is_active,
                last_successfully_used_at,
                created_at,
                updated_at,
                firebase_app_id
            FROM workflows_pushsubscription
            WHERE team_id = $1 AND distinct_id IN (${placeholders}) AND is_active = true ${platformFilter} ${providerFilter} ${appIdFilter}
            ORDER BY last_successfully_used_at DESC NULLS LAST, created_at DESC
            LIMIT 1`

        const rows = (
            await this.postgres.query<PushSubscriptionRow>(
                PostgresUse.COMMON_READ,
                queryString,
                params,
                'findSubscriptionByPersonDistinctIds'
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
            provider: row.provider,
            is_active: row.is_active,
            last_successfully_used_at: row.last_successfully_used_at,
            created_at: row.created_at,
            updated_at: row.updated_at,
        }
    }

    public async updateDistinctId(teamId: number, subscriptionId: string, newDistinctId: string): Promise<void> {
        const queryString = `UPDATE workflows_pushsubscription
            SET distinct_id = $1, updated_at = NOW()
            WHERE id = $2 AND team_id = $3 AND is_active = true`

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            queryString,
            [newDistinctId, subscriptionId, teamId],
            'updatePushSubscriptionDistinctId'
        )
    }

    public async loadPushSubscriptions(
        hogFunction: HogFunctionType,
        inputsToLoad: Record<string, PushSubscriptionInputToLoad>
    ): Promise<Record<string, { value: string | null }>> {
        const returnInputs: Record<string, { value: string | null }> = {}
        const provider = 'fcm' as const

        for (const [key, { distinctId, firebaseAppId, platform }] of Object.entries(inputsToLoad)) {
            returnInputs[key] = { value: null }

            const subscriptions = await this.get({
                teamId: hogFunction.team_id,
                distinctId,
                platform,
                firebaseAppId,
                provider,
            })

            let subscription = subscriptions.shift() ?? null

            if (subscriptions.length > 0) {
                try {
                    await this.deactivateTokens(
                        subscriptions.map((s) => s.token),
                        'duplicate',
                        hogFunction.team_id
                    )
                } catch (error) {
                    logger.warn('Failed to deactivate duplicate push subscription tokens', {
                        teamId: hogFunction.team_id,
                        subscriptionIds: subscriptions.map((s) => s.id).join(','),
                        error,
                    })
                }
            }

            if (!subscription) {
                const relatedDistinctIds = await this.getDistinctIdsForSamePerson(hogFunction.team_id, distinctId)

                if (relatedDistinctIds.length > 0) {
                    subscription = await this.findSubscriptionByPersonDistinctIds(
                        hogFunction.team_id,
                        relatedDistinctIds,
                        platform,
                        firebaseAppId,
                        provider
                    )

                    if (subscription) {
                        await this.updateDistinctId(hogFunction.team_id, subscription.id, distinctId)
                        subscription = {
                            ...subscription,
                            distinct_id: distinctId,
                        }
                    }
                }
            }

            if (subscription && subscription.is_active && subscription.team_id === hogFunction.team_id) {
                returnInputs[key] = { value: subscription.token }
            }
        }

        return returnInputs
    }

    private hashToken(token: string): string {
        return createHash('sha256').update(token, 'utf-8').digest('hex')
    }
}
