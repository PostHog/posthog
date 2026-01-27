import '~/tests/helpers/mocks/date.mock'

import { randomUUID } from 'crypto'
import { DateTime } from 'luxon'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'

import { createHogExecutionGlobals, createHogFunction, insertIntegration } from '../_tests/fixtures'
import { compileHog } from '../templates/compiler'
import { HogFunctionInvocationGlobals, HogFunctionInvocationGlobalsWithInputs, HogFunctionType } from '../types'
import { HogInputsService, formatHogInput } from './hog-inputs.service'
import { PushSubscription } from './managers/push-subscriptions-manager.service'

describe('Hog Inputs', () => {
    let hub: Hub
    let team: Team
    let hogInputsService: HogInputsService

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        hub.SITE_URL = 'http://localhost:8000'
        team = await getFirstTeam(hub)

        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        await insertIntegration(hub.postgres, team.id, {
            id: 1,
            kind: 'slack',
            config: { team: 'foobar' },
            sensitive_config: {
                access_token: hub.encryptedFields.encrypt('token'),
                not_encrypted: 'not-encrypted',
            },
        })

        await insertIntegration(hub.postgres, team.id, {
            id: 2,
            kind: 'oauth',
            config: { team: 'foobar', access_token: 'token' },
            sensitive_config: {
                not_encrypted: 'not-encrypted',
            },
        })

        hogInputsService = new HogInputsService(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('formatInput', () => {
        it('can handle null values in input objects', async () => {
            const globals = {
                ...createHogExecutionGlobals({
                    event: {
                        event: 'test',
                        uuid: 'test-uuid',
                    } as any,
                }),
                inputs: {},
            }

            // Body with null values that should be preserved
            const inputWithNulls = {
                body: {
                    value: {
                        event: '{event}',
                        person: null,
                        userId: null,
                    },
                },
            }

            // Call formatInput directly to test that it handles null values
            const result = await formatHogInput(inputWithNulls, globals)

            // Verify that null values are preserved
            expect(result.body.value.person).toBeNull()
            expect(result.body.value.userId).toBeNull()
            expect(result.body.value.event).toBe('{event}')
        })

        it('can handle deep null and undefined values', async () => {
            const globals = {
                ...createHogExecutionGlobals({
                    event: {
                        event: 'test',
                        uuid: 'test-uuid',
                    } as any,
                }),
                inputs: {},
            }

            const complexInput = {
                body: {
                    value: {
                        data: {
                            first: null,
                            second: undefined,
                            third: {
                                nested: null,
                            },
                        },
                    },
                },
            }

            const result = await formatHogInput(complexInput, globals)

            // Verify all null and undefined values are properly preserved
            expect(result.body.value.data.first).toBeNull()
            expect(result.body.value.data.second).toBeUndefined()
            expect(result.body.value.data.third.nested).toBeNull()
        })
    })

    describe('buildInputs', () => {
        let hogFunction: HogFunctionType
        let globals: HogFunctionInvocationGlobals

        beforeEach(async () => {
            hogFunction = createHogFunction({
                id: 'hog-function-1',
                team_id: team.id,
                name: 'Hog Function 1',
                enabled: true,
                type: 'destination',
                inputs: {
                    hog_templated: {
                        value: 'event: "{event.event}"',
                        templating: 'hog',
                        bytecode: await compileHog('return f\'event: "{event.event}"\''),
                    },
                    liquid_templated: {
                        value: 'event: "{{ event.event }}"',
                        templating: 'liquid',
                    },
                    oauth: { value: 1 },
                },
                inputs_schema: [
                    { key: 'hog_templated', type: 'string', required: true },
                    { key: 'oauth', type: 'integration', required: true },
                ],
            })

            globals = createHogExecutionGlobals()
        })

        it('should template out hog inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.hog_templated).toMatchInlineSnapshot(`"event: "test""`)
        })

        it('should template out liquid inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.liquid_templated).toMatchInlineSnapshot(`"event: "test""`)
        })

        it('should loads inputs with integration inputs', async () => {
            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.oauth).toMatchInlineSnapshot(`
                {
                  "access_token": "$$_access_token_placeholder_1",
                  "access_token_raw": "token",
                  "not_encrypted": "not-encrypted",
                  "team": "foobar",
                }
            `)
        })

        it('access token should be replaced with placeholder', async () => {
            hogFunction = createHogFunction({
                id: 'hog-function-1',
                team_id: team.id,
                name: 'Hog Function 1',
                enabled: true,
                type: 'destination',
                inputs: {
                    hog_templated: {
                        value: 'event: "{event.event}"',
                        templating: 'hog',
                        bytecode: await compileHog('return f\'event: "{event.event}"\''),
                    },
                    liquid_templated: {
                        value: 'event: "{{ event.event }}"',
                        templating: 'liquid',
                    },
                    auth: { value: 2 },
                },
                inputs_schema: [
                    { key: 'hog_templated', type: 'string', required: true },
                    { key: 'auth', type: 'integration', required: true },
                ],
            })

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.auth).toMatchInlineSnapshot(`
                {
                  "access_token": "$$_access_token_placeholder_2",
                  "access_token_raw": "token",
                  "not_encrypted": "not-encrypted",
                  "team": "foobar",
                }
            `)
        })

        it('should not load integrations from a different team', async () => {
            hogFunction.team_id = 100

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)

            expect(inputs.oauth).toMatchInlineSnapshot(`null`)
        })

        it('should add unsubscribe url if email input is present', async () => {
            hogFunction.inputs = {
                email: {
                    templating: 'liquid',
                    value: {
                        to: { email: '{{person.properties.email}}' },
                        html: '<div>Unsubscribe here <a href="{{unsubscribe_url}}">here</a></div>',
                    },
                },
            }

            hogFunction.inputs_schema = [{ key: 'email', type: 'native_email', required: true, templating: true }]

            const inputs = await hogInputsService.buildInputs(hogFunction, globals)
            expect(inputs.email.to.email).toEqual('test@posthog.com')
            expect(inputs.email.html).toEqual(
                `<div>Unsubscribe here <a href="http://localhost:8000/messaging-preferences/eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZWFtX2lkIjoyLCJpZGVudGlmaWVyIjoidGVzdEBwb3N0aG9nLmNvbSIsImlhdCI6MTczNTY4OTYwMCwiZXhwIjoxNzM2Mjk0NDAwLCJhdWQiOiJwb3N0aG9nOm1lc3NhZ2luZzpzdWJzY3JpcHRpb25fcHJlZmVyZW5jZXMifQ.pBh-COzTEyApuxe8J5sViPanp1lV1IClepOTVFZNhIs/">here</a></div>`
            )
        })
    })

    describe('loadPushSubscriptionInputs', () => {
        const insertPushSubscription = async (
            teamId: number,
            distinctId: string,
            token: string,
            platform: 'android' | 'ios',
            isActive: boolean = true,
            provider: 'fcm' | 'apns' = 'fcm',
            firebaseAppId: string | null = null
        ): Promise<PushSubscription> => {
            const id = randomUUID()
            const encryptedToken = hub.encryptedFields.encrypt(token)
            const tokenHash = require('crypto').createHash('sha256').update(token, 'utf-8').digest('hex')

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO workflows_pushsubscription 
                 (id, team_id, distinct_id, token, token_hash, platform, provider, firebase_app_id, is_active, created_at, updated_at)
                 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
                 RETURNING *`,
                [id, teamId, distinctId, encryptedToken, tokenHash, platform, provider, firebaseAppId, isActive],
                'insertPushSubscription'
            )

            return {
                id,
                team_id: teamId,
                distinct_id: distinctId,
                token,
                platform,
                provider,
                is_active: isActive,
                last_successfully_used_at: null,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
            }
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

        const setupFirebaseIntegration = () => {
            const firebaseIntegration = {
                id: 1,
                team_id: team.id,
                kind: 'firebase',
                config: { project_id: 'test-project' },
                sensitive_config: {
                    key_info: {
                        project_id: 'test-project',
                    },
                },
            }
            hub.integrationManager.getMany = jest.fn().mockResolvedValue({ 1: firebaseIntegration })
            return firebaseIntegration
        }

        let hogFunction: HogFunctionType
        let globals: HogFunctionInvocationGlobalsWithInputs

        beforeEach(() => {
            hogFunction = createHogFunction({
                id: 'hog-function-1',
                team_id: team.id,
                name: 'Hog Function 1',
                enabled: true,
                type: 'destination',
                inputs: {},
                inputs_schema: [],
            })

            globals = {
                ...createHogExecutionGlobals(),
                inputs: {},
            }
        })

        it('returns empty object when no push subscription inputs exist', async () => {
            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({})
        })

        it('returns empty object when input value is not a string', async () => {
            hogFunction.inputs_schema = [
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                push_subscription_distinct_id: {
                    value: 123,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({})
        })

        it('resolves distinct_id to FCM token for active subscription', async () => {
            setupFirebaseIntegration()
            const distinctId = 'user-123'
            const matchingToken = 'fcm-token-abc123'
            const nonMatchingToken = 'fcm-token-xyz789'
            // Insert subscription with matching firebase_app_id
            await insertPushSubscription(team.id, distinctId, matchingToken, 'android', true, 'fcm', 'test-project')
            // Insert subscription with different firebase_app_id to verify filtering
            await insertPushSubscription(team.id, distinctId, nonMatchingToken, 'android', true, 'fcm', 'other-project')

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            // Should return matching token (test-project), not the non-matching one (other-project)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: matchingToken,
                },
            })
            expect(result.push_subscription_distinct_id.value).not.toBe(nonMatchingToken)
        })

        it('returns null for inactive subscription', async () => {
            setupFirebaseIntegration()
            const distinctId = 'user-123'
            const token = 'fcm-token-abc123'
            await insertPushSubscription(team.id, distinctId, token, 'android', false, 'fcm', 'test-project')

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: null,
                },
            })
        })

        it('returns null for subscription from different team', async () => {
            setupFirebaseIntegration()
            const distinctId = 'user-123'
            const token = 'fcm-token-abc123'
            await insertPushSubscription(999, distinctId, token, 'android', true, 'fcm', 'test-project')

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: null,
                },
            })
        })

        it('filters by platform when specified', async () => {
            setupFirebaseIntegration()
            const distinctId = 'user-123'
            const androidToken = 'fcm-token-android'
            const iosToken = 'fcm-token-ios'
            await insertPushSubscription(team.id, distinctId, androidToken, 'android', true, 'fcm', 'test-project')
            await insertPushSubscription(team.id, distinctId, iosToken, 'ios', true, 'apns')

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: androidToken,
                },
            })
        })

        it('resolves liquid template to distinct_id', async () => {
            setupFirebaseIntegration()
            const distinctId = 'user-123'
            const token = 'fcm-token-abc123'
            await insertPushSubscription(team.id, distinctId, token, 'android', true, 'fcm', 'test-project')

            globals.person = {
                id: 'person-1',
                name: distinctId,
                url: 'http://localhost:8000/persons/1',
                properties: {},
            }

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                    templating: 'liquid',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: '{{ person.name }}',
                    templating: 'liquid',
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: token,
                },
            })
        })

        it('resolves hog template to distinct_id', async () => {
            setupFirebaseIntegration()
            const distinctId = 'user-123'
            const token = 'fcm-token-abc123'
            await insertPushSubscription(team.id, distinctId, token, 'android', true, 'fcm', 'test-project')

            globals.event = {
                ...globals.event!,
                distinct_id: distinctId,
            }

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                    templating: 'hog',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: distinctId,
                    templating: 'hog',
                    bytecode: await compileHog(`return event.distinct_id`),
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: token,
                },
            })
        })

        it('returns null when template resolution fails', async () => {
            setupFirebaseIntegration()
            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                    templating: 'liquid',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: '{{ invalid.template }}',
                    templating: 'liquid',
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: null,
                },
            })
        })

        it('falls back to related distinct_ids for same person and updates distinct_id', async () => {
            setupFirebaseIntegration()
            const originalDistinctId = 'user-original'
            const newDistinctId = 'user-new'
            const token = 'fcm-token-abc123'

            // Create person with original distinct_id
            const personId = await insertPerson(team.id)
            await insertPersonDistinctId(team.id, personId, originalDistinctId)
            await insertPersonDistinctId(team.id, personId, newDistinctId)

            // Subscription exists with original distinct_id
            await insertPushSubscription(team.id, originalDistinctId, token, 'android', true, 'fcm', 'test-project')

            // But we're looking for new distinct_id
            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: newDistinctId,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: token,
                },
            })

            // Verify the subscription was updated to use the new distinct_id
            const tokenHash = require('crypto').createHash('sha256').update(token, 'utf-8').digest('hex')
            const updatedSub = await hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT distinct_id FROM workflows_pushsubscription WHERE team_id = $1 AND token_hash = $2 LIMIT 1`,
                [team.id, tokenHash],
                'checkUpdatedDistinctId'
            )
            expect(updatedSub.rows[0]?.distinct_id).toBe(newDistinctId)
        })

        it('handles multiple push subscription inputs', async () => {
            setupFirebaseIntegration()
            const distinctId1 = 'user-1'
            const distinctId2 = 'user-2'
            const token1 = 'fcm-token-1'
            const token2 = 'fcm-token-2'
            await insertPushSubscription(team.id, distinctId1, token1, 'android', true, 'fcm', 'test-project')
            await insertPushSubscription(team.id, distinctId2, token2, 'ios', true, 'apns')

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'android_token',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
                {
                    key: 'ios_token',
                    type: 'push_subscription_distinct_id',
                    platform: 'ios',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                android_token: {
                    value: distinctId1,
                },
                ios_token: {
                    value: distinctId2,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                android_token: {
                    value: token1,
                },
                ios_token: {
                    value: token2,
                },
            })
        })

        it('filters by provider when firebase_account integration is present', async () => {
            const distinctId = 'user-123'
            const fcmToken = 'fcm-token-abc123'
            const apnsToken = 'apns-token-xyz789'

            // Insert subscriptions with different providers
            await insertPushSubscription(team.id, distinctId, fcmToken, 'android', true, 'fcm', 'app-123')
            await insertPushSubscription(team.id, distinctId, apnsToken, 'ios', true, 'apns')

            // Mock firebase_account integration
            const firebaseIntegration = {
                id: 1,
                team_id: team.id,
                kind: 'firebase',
                config: { project_id: 'test-project' },
                sensitive_config: {},
            }
            hub.integrationManager.getMany = jest.fn().mockResolvedValue({ 1: firebaseIntegration })

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)

            // Should only return FCM token since provider filter is set to 'fcm'
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: fcmToken,
                },
            })
        })

        it('throws error when integrationInputs is not provided', async () => {
            const distinctId = 'user-123'

            hogFunction.inputs_schema = [
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            await expect(hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, undefined)).rejects.toThrow(
                /firebase_account integration is required for push subscription inputs/
            )
        })

        it('throws error when firebase_account integration is not present in integrationInputs', async () => {
            const distinctId = 'user-123'

            hogFunction.inputs_schema = [
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            // integrationInputs exists but doesn't have firebase_account
            const integrationInputs = {}

            await expect(
                hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            ).rejects.toThrow(/firebase_account integration is required for push subscription inputs but was not found/)
        })

        it('throws error when firebase_account integration value is null', async () => {
            const distinctId = 'user-123'

            hogFunction.inputs_schema = [
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            // integrationInputs has firebase_account but value is null
            const integrationInputs = {
                firebase_account: {
                    value: null,
                },
            }

            await expect(
                hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            ).rejects.toThrow(/firebase_account integration is required for push subscription inputs but was not found/)
        })

        it('throws error when firebase_account integration is present but firebase_app_id is missing', async () => {
            const distinctId = 'user-123'

            // Mock firebase_account integration without key_info.project_id
            const firebaseIntegration = {
                id: 1,
                team_id: team.id,
                kind: 'firebase',
                config: {},
                sensitive_config: {
                    // key_info exists but doesn't have project_id
                    key_info: {},
                },
            }
            hub.integrationManager.getMany = jest.fn().mockResolvedValue({ 1: firebaseIntegration })

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: distinctId,
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)

            await expect(
                hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            ).rejects.toThrow(/Firebase app ID.*not found.*firebase_account integration/)
        })

        it('returns null when subscription not found', async () => {
            // Mock firebase_account integration
            const firebaseIntegration = {
                id: 1,
                team_id: team.id,
                kind: 'firebase',
                config: { project_id: 'test-project' },
                sensitive_config: {
                    key_info: {
                        project_id: 'test-project',
                    },
                },
            }
            hub.integrationManager.getMany = jest.fn().mockResolvedValue({ 1: firebaseIntegration })

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: 'non-existent-user',
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: null,
                },
            })
        })

        it('handles liquid template with double braces detection', async () => {
            setupFirebaseIntegration()
            const distinctId = 'user-123'
            const token = 'fcm-token-abc123'
            await insertPushSubscription(team.id, distinctId, token, 'android', true, 'fcm', 'test-project')

            globals.person = {
                id: 'person-1',
                name: distinctId,
                url: 'http://localhost:8000/persons/1',
                properties: {},
            }

            hogFunction.inputs_schema = [
                {
                    key: 'firebase_account',
                    type: 'integration',
                    integration: 'firebase',
                },
                {
                    key: 'push_subscription_distinct_id',
                    type: 'push_subscription_distinct_id',
                    platform: 'android',
                },
            ]
            hogFunction.inputs = {
                firebase_account: {
                    value: { integrationId: 1 },
                },
                push_subscription_distinct_id: {
                    value: '{{ person.name }}',
                    // No templating specified, but contains {{ so should use liquid
                },
            }

            const integrationInputs = await hogInputsService.loadIntegrationInputs(hogFunction)
            const result = await hogInputsService.loadPushSubscriptionInputs(hogFunction, globals, integrationInputs)
            expect(result).toEqual({
                push_subscription_distinct_id: {
                    value: token,
                },
            })
        })
    })
})
