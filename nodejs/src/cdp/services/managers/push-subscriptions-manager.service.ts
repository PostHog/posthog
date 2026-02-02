import { createHash } from 'crypto'
import { Counter } from 'prom-client'

import { parseJSON } from '~/utils/json-parse'

import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { HogFunctionType } from '../../types'
import { EncryptedFields } from '../../utils/encryption-utils'

export type FcmErrorDetail = { '@type'?: string; errorCode?: string }

const getDistinctIdsForSamePersonCounter = new Counter({
    name: 'cdp_push_subscription_get_distinct_ids_for_same_person_total',
    help: 'Total number of getDistinctIdsForSamePerson calls',
})

export type PushSubscriptionGetArgs = {
    teamId: number
    distinctId: string
    platform?: 'android' | 'ios'
    fcmProjectId?: string
    provider?: 'fcm' | 'apns'
}

const toKey = (args: PushSubscriptionGetArgs): string => {
    // Use JSON encoding to safely handle distinctIds containing colons or other special characters
    return JSON.stringify([
        args.teamId,
        args.distinctId,
        args.platform ?? 'all',
        args.fcmProjectId ?? 'all',
        args.provider ?? 'all',
    ])
}

const fromKey = (key: string): PushSubscriptionGetArgs => {
    // Parse JSON-encoded key to safely handle distinctIds containing colons or other special characters
    const [teamId, distinctId, platform, fcmProjectId, provider] = parseJSON(key)
    return {
        teamId: parseInt(teamId),
        distinctId,
        platform: platform === 'all' ? undefined : (platform as 'android' | 'ios'),
        fcmProjectId: fcmProjectId === 'all' ? undefined : fcmProjectId,
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
    fcm_project_id: string | null
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
    fcm_project_id: string | null
}

export type PushSubscriptionInputToLoad = {
    distinctId: string
    fcmProjectId: string
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
                fcm_project_id
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
            fcm_project_id: row.fcm_project_id,
        }
    }

    private async fetchPushSubscriptions(ids: string[]): Promise<Record<string, PushSubscription[] | undefined>> {
        const subscriptionArgs = ids.map(fromKey)

        const conditions: string[] = []
        const params: any[] = []
        let paramIdx = 1

        for (const args of subscriptionArgs) {
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

            if (args.fcmProjectId) {
                conditionParts.push(`(fcm_project_id = $${paramIdx++} OR fcm_project_id IS NULL)`)
                params.push(args.fcmProjectId)
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
                fcm_project_id
            FROM workflows_pushsubscription
            WHERE ${conditions.join(' OR ')}
            ORDER BY last_successfully_used_at DESC NULLS LAST, created_at DESC`

        const response = await this.postgres.query<PushSubscriptionRow>(
            PostgresUse.COMMON_READ,
            queryString,
            params,
            'fetchPushSubscriptions'
        )
        const subscriptionRows = response.rows

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
                    !args.fcmProjectId || args.fcmProjectId === row.fcm_project_id || row.fcm_project_id === null

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
                        fcm_project_id: row.fcm_project_id,
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

    public async deactivateByTokens(tokens: string[], reason: string, teamId: number): Promise<void> {
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

    public async deactivateByIds(subscriptionIds: string[], reason: string, teamId: number): Promise<void> {
        if (subscriptionIds.length === 0) {
            return
        }
        const queryString = `UPDATE workflows_pushsubscription
            SET is_active = false, disabled_reason = $1
            WHERE team_id = $2 AND id = ANY($3::uuid[]) AND is_active = true`

        await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            queryString,
            [reason, teamId, subscriptionIds],
            'deactivatePushSubscriptionByIds'
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
                await this.deactivateByTokens([fcmToken], 'unregistered token', teamId)
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
                    await this.deactivateByTokens([fcmToken], 'invalid token', teamId)
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
        fcmProjectId?: string,
        provider?: 'fcm' | 'apns'
    ): Promise<PushSubscription | null> {
        if (distinctIds.length === 0) {
            return null
        }

        const placeholders = distinctIds.map((_, idx) => `$${idx + 2}`).join(', ')
        let paramIndex = distinctIds.length + 2
        const platformFilter = platform ? `AND platform = $${paramIndex++}` : ''
        const providerFilter = provider ? `AND provider = $${paramIndex++}` : ''
        const appIdFilter = fcmProjectId ? `AND (fcm_project_id = $${paramIndex++} OR fcm_project_id IS NULL)` : ''

        const params: any[] = [teamId, ...distinctIds]
        if (platform) {
            params.push(platform)
        }
        if (provider) {
            params.push(provider)
        }
        if (fcmProjectId) {
            params.push(fcmProjectId)
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
                fcm_project_id
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
            fcm_project_id: row.fcm_project_id,
        }
    }

    public async findSubscriptionsByPersonDistinctIds(
        teamId: number,
        distinctIds: string[],
        platform?: 'android' | 'ios',
        fcmProjectId?: string,
        provider?: 'fcm' | 'apns'
    ): Promise<PushSubscription[]> {
        if (distinctIds.length === 0) {
            return []
        }

        const placeholders = distinctIds.map((_, idx) => `$${idx + 2}`).join(', ')
        let paramIndex = distinctIds.length + 2
        const platformFilter = platform ? `AND platform = $${paramIndex++}` : ''
        const providerFilter = provider ? `AND provider = $${paramIndex++}` : ''
        const appIdFilter = fcmProjectId ? `AND (fcm_project_id = $${paramIndex++} OR fcm_project_id IS NULL)` : ''

        const params: any[] = [teamId, ...distinctIds]
        if (platform) {
            params.push(platform)
        }
        if (provider) {
            params.push(provider)
        }
        if (fcmProjectId) {
            params.push(fcmProjectId)
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
                fcm_project_id
            FROM workflows_pushsubscription
            WHERE team_id = $1 AND distinct_id IN (${placeholders}) AND is_active = true ${platformFilter} ${providerFilter} ${appIdFilter}
            ORDER BY last_successfully_used_at DESC NULLS LAST, created_at DESC`

        const { rows } = await this.postgres.query<PushSubscriptionRow>(
            PostgresUse.COMMON_READ,
            queryString,
            params,
            'findSubscriptionsByPersonDistinctIds'
        )

        return rows.map((row) => {
            const decryptedToken =
                this.encryptedFields.decrypt(row.token, { ignoreDecryptionErrors: true }) ?? row.token
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
                fcm_project_id: row.fcm_project_id,
            }
        })
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
        if (Object.keys(inputsToLoad).length === 0) {
            return {}
        }

        const returnInputs: Record<string, { value: string | null }> = {}
        const provider = 'fcm' as const

        const entries = Object.entries(inputsToLoad).map(([key, { distinctId, fcmProjectId, platform }]) => ({
            inputKey: key,
            getArgs: {
                teamId: hogFunction.team_id,
                distinctId,
                platform,
                fcmProjectId,
                provider,
            },
        }))

        const argsForGetMany = entries.map((e) => e.getArgs)
        const resultsByGetKey = await this.getMany(argsForGetMany)

        const duplicatesToDeactivate: string[] = []

        for (const { inputKey, getArgs } of entries) {
            returnInputs[inputKey] = { value: null }

            const subscriptions = resultsByGetKey[toKey(getArgs)] ?? []

            let subscription = subscriptions.shift() ?? null

            duplicatesToDeactivate.push(...subscriptions.map((s) => s.id))

            if (!subscription) {
                const { distinctId } = getArgs
                const relatedDistinctIds = await this.getDistinctIdsForSamePerson(hogFunction.team_id, distinctId)

                if (relatedDistinctIds.length > 0) {
                    const personSubscriptions = await this.findSubscriptionsByPersonDistinctIds(
                        hogFunction.team_id,
                        relatedDistinctIds,
                        getArgs.platform,
                        getArgs.fcmProjectId,
                        provider
                    )

                    subscription = personSubscriptions.shift() ?? null

                    duplicatesToDeactivate.push(...personSubscriptions.map((s) => s.id))

                    if (subscription) {
                        await this.updateDistinctId(hogFunction.team_id, subscription.id, distinctId)
                        subscription = {
                            ...subscription,
                            distinct_id: distinctId,
                        }
                    }
                }
            }

            if (subscription?.is_active) {
                returnInputs[inputKey] = { value: subscription.token }
            }
        }

        try {
            await this.deactivateByIds([...new Set(duplicatesToDeactivate)], 'duplicate', hogFunction.team_id)
        } catch (error) {
            logger.warn('Failed to deactivate duplicate push subscriptions', {
                teamId: hogFunction.team_id,
                duplicatesToDeactivate,
                error,
            })
        }

        return returnInputs
    }

    private hashToken(token: string): string {
        return createHash('sha256').update(token, 'utf-8').digest('hex')
    }
}
