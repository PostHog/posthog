import '~/tests/helpers/mocks/date.mock'

import { createHash, randomUUID } from 'crypto'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'

import { createHogFunction } from '../../_tests/fixtures'
import { HogFunctionType } from '../../types'
import { PushSubscriptionInputToLoad, PushSubscriptionsManagerService } from './push-subscriptions-manager.service'

describe('PushSubscriptionsManagerService', () => {
    describe('loadPushSubscriptions', () => {
        let hub: Hub
        let team: Team
        let manager: PushSubscriptionsManagerService
        let hogFunction: HogFunctionType

        const insertPushSubscription = async (
            teamId: number,
            distinctId: string,
            token: string,
            platform: 'android' | 'ios',
            isActive: boolean = true,
            provider: 'fcm' | 'apns' = 'fcm',
            fcmProjectId: string | null = null
        ): Promise<void> => {
            const id = randomUUID()
            const encryptedToken = hub.encryptedFields.encrypt(token)
            const tokenHash = createHash('sha256').update(token, 'utf-8').digest('hex')

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO workflows_pushsubscription 
                 (id, team_id, distinct_id, token, token_hash, platform, provider, fcm_project_id, is_active, created_at, updated_at)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
                 RETURNING *`,
                [id, teamId, distinctId, encryptedToken, tokenHash, platform, provider, fcmProjectId, isActive],
                'insertPushSubscription'
            )
        }

        const insertPersonDistinctId = async (teamId: number, personId: number, distinctId: string): Promise<void> => {
            await hub.postgres.query(
                PostgresUse.PERSONS_WRITE,
                `INSERT INTO posthog_persondistinctid (distinct_id, person_id, team_id, version)
                 VALUES ($1, $2, $3, 0)
                 ON CONFLICT DO NOTHING`,
                [distinctId, personId, teamId],
                'insertPersonDistinctId'
            )
        }

        const insertPerson = async (teamId: number): Promise<number> => {
            const personUuid = randomUUID()
            const result = await hub.postgres.query<{ id: number }>(
                PostgresUse.PERSONS_WRITE,
                `INSERT INTO posthog_person (uuid, team_id, created_at, properties, properties_last_updated_at, properties_last_operation, is_identified, version)
                 VALUES ($1, $2, NOW(), '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, true, 0)
                 RETURNING id`,
                [personUuid, teamId],
                'insertPerson'
            )
            return result.rows[0].id
        }

        beforeEach(async () => {
            await resetTestDatabase()
            hub = await createHub()
            team = await getFirstTeam(hub)
            manager = new PushSubscriptionsManagerService(hub.postgres, hub.encryptedFields)
            hogFunction = createHogFunction({
                id: 'hog-function-1',
                team_id: team.id,
                name: 'Hog Function 1',
                enabled: true,
                type: 'destination',
                inputs: {},
                inputs_schema: [],
            })
        })

        afterEach(async () => {
            if (hub) {
                await closeHub(hub)
            }
        })

        it('returns empty object when no inputs to load', async () => {
            const result = await manager.loadPushSubscriptions(hogFunction, {})
            expect(result).toEqual({})
        })

        it('resolves distinct_id to FCM token for active subscription', async () => {
            const distinctId = 'user-123'
            const matchingToken = 'fcm-token-abc123'
            const nonMatchingToken = 'fcm-token-xyz789'
            await insertPushSubscription(team.id, distinctId, matchingToken, 'android', true, 'fcm', 'test-project')
            await insertPushSubscription(team.id, distinctId, nonMatchingToken, 'android', true, 'fcm', 'other-project')

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId,
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)
            expect(result).toEqual({
                push_subscription: { value: matchingToken },
            })
            expect(result.push_subscription.value).not.toBe(nonMatchingToken)
        })

        it('deactivates duplicate subscriptions with reason "duplicate" when multiple match', async () => {
            const distinctId = 'user-123'
            const token1 = 'fcm-token-first'
            const token2 = 'fcm-token-second'
            const token3 = 'fcm-token-third'
            await insertPushSubscription(team.id, distinctId, token1, 'android', true, 'fcm', 'test-project')
            await insertPushSubscription(team.id, distinctId, token2, 'android', true, 'fcm', 'test-project')
            await insertPushSubscription(team.id, distinctId, token3, 'android', true, 'fcm', 'test-project')

            const deactivateSpy = jest.spyOn(manager, 'deactivateByIds').mockResolvedValue(undefined)

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId,
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)

            expect(result.push_subscription.value).toBeTruthy()
            expect([token1, token2, token3]).toContain(result.push_subscription.value)
            expect(deactivateSpy).toHaveBeenCalledTimes(1)
            expect(deactivateSpy).toHaveBeenCalledWith(expect.any(Array), 'duplicate', team.id)
            const deactivatedIds = deactivateSpy.mock.calls[0][0] as string[]
            expect(deactivatedIds).toHaveLength(2)
        })

        it('returns null for inactive subscription', async () => {
            const distinctId = 'user-123'
            const token = 'fcm-token-abc123'
            await insertPushSubscription(team.id, distinctId, token, 'android', false, 'fcm', 'test-project')

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId,
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)
            expect(result).toEqual({
                push_subscription: { value: null },
            })
        })

        it('returns null for subscription from different team', async () => {
            const distinctId = 'user-123'
            const token = 'fcm-token-abc123'
            await insertPushSubscription(999, distinctId, token, 'android', true, 'fcm', 'test-project')

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId,
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)
            expect(result).toEqual({
                push_subscription: { value: null },
            })
        })

        it('filters by platform when specified', async () => {
            const distinctId = 'user-123'
            const androidToken = 'fcm-token-android'
            const iosToken = 'fcm-token-ios'
            await insertPushSubscription(team.id, distinctId, androidToken, 'android', true, 'fcm', 'test-project')
            await insertPushSubscription(team.id, distinctId, iosToken, 'ios', true, 'apns')

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId,
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)
            expect(result).toEqual({
                push_subscription: { value: androidToken },
            })
        })

        it('falls back to related distinct_ids for same person and updates distinct_id', async () => {
            const originalDistinctId = 'user-original'
            const newDistinctId = 'user-new'
            const token = 'fcm-token-abc123'

            const personId = await insertPerson(team.id)
            await insertPersonDistinctId(team.id, personId, originalDistinctId)
            await insertPersonDistinctId(team.id, personId, newDistinctId)
            await insertPushSubscription(team.id, originalDistinctId, token, 'android', true, 'fcm', 'test-project')

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId: newDistinctId,
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)
            expect(result).toEqual({
                push_subscription: { value: token },
            })

            const tokenHash = createHash('sha256').update(token, 'utf-8').digest('hex')
            const updatedSub = await hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT distinct_id FROM workflows_pushsubscription WHERE team_id = $1 AND token_hash = $2 LIMIT 1`,
                [team.id, tokenHash],
                'checkUpdatedDistinctId'
            )
            expect(updatedSub.rows[0]?.distinct_id).toBe(newDistinctId)
        })

        it('deactivates duplicate subscriptions from person-merge path', async () => {
            const distinctIdA = 'user-a'
            const distinctIdB = 'user-b'
            const tokenB1 = 'fcm-token-b1'
            const tokenB2 = 'fcm-token-b2'

            const personId = await insertPerson(team.id)
            await insertPersonDistinctId(team.id, personId, distinctIdA)
            await insertPersonDistinctId(team.id, personId, distinctIdB)
            await insertPushSubscription(team.id, distinctIdB, tokenB1, 'android', true, 'fcm', 'test-project')
            await insertPushSubscription(team.id, distinctIdB, tokenB2, 'android', true, 'fcm', 'test-project')

            const deactivateSpy = jest.spyOn(manager, 'deactivateByIds').mockResolvedValue(undefined)

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId: distinctIdA,
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)

            expect([tokenB1, tokenB2]).toContain(result.push_subscription.value)
            expect(deactivateSpy).toHaveBeenCalledTimes(1)
            const deactivatedIds = deactivateSpy.mock.calls[0][0] as string[]
            expect(deactivatedIds).toHaveLength(1)
        })

        it('handles multiple push subscription inputs', async () => {
            const distinctId1 = 'user-1'
            const distinctId2 = 'user-2'
            const token1 = 'fcm-token-1'
            const token2 = 'fcm-token-2'
            await insertPushSubscription(team.id, distinctId1, token1, 'android', true, 'fcm', 'test-project')
            await insertPushSubscription(team.id, distinctId2, token2, 'ios', true, 'apns')

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                android_token: {
                    distinctId: distinctId1,
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
                ios_token: {
                    distinctId: distinctId2,
                    fcmProjectId: 'test-project',
                    platform: 'ios',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)
            expect(result).toEqual({
                android_token: { value: token1 },
                ios_token: { value: token2 },
            })
        })

        it('filters by provider (fcm) so only FCM token is returned when user has both FCM and APNS subscriptions', async () => {
            const distinctId = 'user-123'
            const fcmToken = 'fcm-token-abc123'
            const apnsToken = 'apns-token-xyz789'

            await insertPushSubscription(team.id, distinctId, fcmToken, 'android', true, 'fcm', 'app-123')
            await insertPushSubscription(team.id, distinctId, apnsToken, 'ios', true, 'apns')

            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId,
                    fcmProjectId: 'app-123',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)
            expect(result).toEqual({
                push_subscription: { value: fcmToken },
            })
        })

        it('returns null when subscription not found', async () => {
            const inputsToLoad: Record<string, PushSubscriptionInputToLoad> = {
                push_subscription: {
                    distinctId: 'non-existent-user',
                    fcmProjectId: 'test-project',
                    platform: 'android',
                },
            }
            const result = await manager.loadPushSubscriptions(hogFunction, inputsToLoad)
            expect(result).toEqual({
                push_subscription: { value: null },
            })
        })
    })
})
