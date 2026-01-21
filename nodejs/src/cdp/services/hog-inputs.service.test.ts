import '~/tests/helpers/mocks/date.mock'

import { DateTime } from 'luxon'

import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { createHogExecutionGlobals, createHogFunction, insertIntegration } from '../_tests/fixtures'
import { compileHog } from '../templates/compiler'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../types'
import { HogInputsService, formatHogInput } from './hog-inputs.service'

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

    describe('push_subscriptions deduplication', () => {
        let pushSubscriptionsManager: any

        beforeEach(() => {
            pushSubscriptionsManager = hogInputsService['pushSubscriptionsManager']
        })

        it('does not query PersonDistinctId when all subscriptions have person_id', async () => {
            const mockSubscriptions = [
                {
                    id: 'sub-1',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-1',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: 123,
                },
            ]

            jest.spyOn(pushSubscriptionsManager, 'get').mockResolvedValue(mockSubscriptions)
            jest.spyOn(pushSubscriptionsManager, 'updatePersonIds').mockResolvedValue(undefined)
            jest.spyOn(pushSubscriptionsManager, 'deactivateSubscriptionsByIds').mockResolvedValue(undefined)
            const postgresQuerySpy = jest.spyOn(hub.postgres, 'query')

            const hogFunction = createHogFunction({
                team_id: team.id,
                inputs_schema: [{ key: 'push_sub', type: 'push_subscription', required: true }],
            })

            const globals = createHogExecutionGlobals({
                event: { distinct_id: 'distinct-1' } as any,
            })

            await hogInputsService.buildInputs(hogFunction, globals)

            expect(postgresQuerySpy).not.toHaveBeenCalled()
            expect(pushSubscriptionsManager.updatePersonIds).not.toHaveBeenCalled()
        })

        it('queries PersonDistinctId and updates subscriptions without person_id', async () => {
            const mockSubscriptions = [
                {
                    id: 'sub-1',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-1',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: null,
                },
            ]

            jest.spyOn(pushSubscriptionsManager, 'get').mockResolvedValue(mockSubscriptions)
            jest.spyOn(pushSubscriptionsManager, 'updatePersonIds').mockResolvedValue(undefined)
            jest.spyOn(pushSubscriptionsManager, 'deactivateSubscriptionsByIds').mockResolvedValue(undefined)
            jest.spyOn(hub.postgres, 'query').mockResolvedValue({
                rows: [{ person_id: 456 }],
            } as any)

            const hogFunction = createHogFunction({
                team_id: team.id,
                inputs_schema: [{ key: 'push_sub', type: 'push_subscription', required: true }],
            })

            const globals = createHogExecutionGlobals({
                event: { distinct_id: 'distinct-1' } as any,
            })

            await hogInputsService.buildInputs(hogFunction, globals)

            expect(hub.postgres.query).toHaveBeenCalledWith(
                expect.anything(),
                expect.stringContaining('SELECT person_id'),
                expect.anything(),
                expect.anything()
            )
            expect(pushSubscriptionsManager.updatePersonIds).toHaveBeenCalledWith(team.id, [
                { subscriptionId: 'sub-1', personId: 456 },
            ])
        })

        it('groups subscriptions by person_id + token_hash and keeps latest', async () => {
            const mockSubscriptions = [
                {
                    id: 'sub-1',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-1',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: 123,
                },
                {
                    id: 'sub-2',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-2',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-02T00:00:00Z',
                    updated_at: '2025-01-02T00:00:00Z',
                    person_id: 123,
                },
            ]

            jest.spyOn(pushSubscriptionsManager, 'get').mockResolvedValue(mockSubscriptions)
            jest.spyOn(pushSubscriptionsManager, 'updatePersonIds').mockResolvedValue(undefined)
            jest.spyOn(pushSubscriptionsManager, 'deactivateSubscriptionsByIds').mockResolvedValue(undefined)
            jest.spyOn(hub.postgres, 'query').mockResolvedValue({ rows: [] } as any)

            const hogFunction = createHogFunction({
                team_id: team.id,
                inputs_schema: [{ key: 'push_sub', type: 'push_subscription', required: true }],
            })

            const globals = createHogExecutionGlobals({
                event: { distinct_id: 'distinct-1' } as any,
            })

            const result = await hogInputsService.buildInputsWithGlobals(hogFunction, globals)

            expect(pushSubscriptionsManager.deactivateSubscriptionsByIds).toHaveBeenCalledWith(
                team.id,
                ['sub-1'],
                'Disabled because user+device has a more recent token'
            )
            expect(result.push_subscriptions).toEqual([{ id: 'sub-2' }])
        })

        it('considers subscriptions with existing person_id when grouping', async () => {
            const mockSubscriptions = [
                {
                    id: 'sub-existing',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-1',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: 123,
                },
                {
                    id: 'sub-new',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-2',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-02T00:00:00Z',
                    updated_at: '2025-01-02T00:00:00Z',
                    person_id: null,
                },
            ]

            jest.spyOn(pushSubscriptionsManager, 'get').mockResolvedValue(mockSubscriptions)
            jest.spyOn(pushSubscriptionsManager, 'updatePersonIds').mockResolvedValue(undefined)
            jest.spyOn(pushSubscriptionsManager, 'deactivateSubscriptionsByIds').mockResolvedValue(undefined)
            jest.spyOn(hub.postgres, 'query').mockResolvedValue({
                rows: [{ person_id: 123 }],
            } as any)

            const hogFunction = createHogFunction({
                team_id: team.id,
                inputs_schema: [{ key: 'push_sub', type: 'push_subscription', required: true }],
            })

            const globals = createHogExecutionGlobals({
                event: { distinct_id: 'distinct-1' } as any,
            })

            const result = await hogInputsService.buildInputsWithGlobals(hogFunction, globals)

            // Both subscriptions should be grouped together by person_id (123) + token_hash (hash-1)
            // sub-new should be kept (newer), sub-existing should be disabled
            expect(pushSubscriptionsManager.updatePersonIds).toHaveBeenCalledWith(team.id, [
                { subscriptionId: 'sub-new', personId: 123 },
            ])
            expect(pushSubscriptionsManager.deactivateSubscriptionsByIds).toHaveBeenCalledWith(
                team.id,
                ['sub-existing'],
                'Disabled because user+device has a more recent token'
            )
            expect(result.push_subscriptions).toEqual([{ id: 'sub-new' }])
        })

        it('keeps all subscriptions when they have different token_hashes', async () => {
            const mockSubscriptions = [
                {
                    id: 'sub-1',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-1',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: 123,
                },
                {
                    id: 'sub-2',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-2',
                    token_hash: 'hash-2',
                    platform: 'ios' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: 123,
                },
            ]

            jest.spyOn(pushSubscriptionsManager, 'get').mockResolvedValue(mockSubscriptions)
            jest.spyOn(pushSubscriptionsManager, 'updatePersonIds').mockResolvedValue(undefined)
            jest.spyOn(pushSubscriptionsManager, 'deactivateSubscriptionsByIds').mockResolvedValue(undefined)
            jest.spyOn(hub.postgres, 'query').mockResolvedValue({ rows: [] } as any)

            const hogFunction = createHogFunction({
                team_id: team.id,
                inputs_schema: [{ key: 'push_sub', type: 'push_subscription', required: true }],
            })

            const globals = createHogExecutionGlobals({
                event: { distinct_id: 'distinct-1' } as any,
            })

            const result = await hogInputsService.buildInputsWithGlobals(hogFunction, globals)

            expect(pushSubscriptionsManager.deactivateSubscriptionsByIds).not.toHaveBeenCalled()
            expect(result.push_subscriptions).toEqual([{ id: 'sub-1' }, { id: 'sub-2' }])
        })

        it('keeps all subscriptions when they have different person_ids', async () => {
            const mockSubscriptions = [
                {
                    id: 'sub-1',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-1',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: 123,
                },
                {
                    id: 'sub-2',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-2',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: 456,
                },
            ]

            jest.spyOn(pushSubscriptionsManager, 'get').mockResolvedValue(mockSubscriptions)
            jest.spyOn(pushSubscriptionsManager, 'updatePersonIds').mockResolvedValue(undefined)
            jest.spyOn(pushSubscriptionsManager, 'deactivateSubscriptionsByIds').mockResolvedValue(undefined)
            jest.spyOn(hub.postgres, 'query').mockResolvedValue({ rows: [] } as any)

            const hogFunction = createHogFunction({
                team_id: team.id,
                inputs_schema: [{ key: 'push_sub', type: 'push_subscription', required: true }],
            })

            const globals = createHogExecutionGlobals({
                event: { distinct_id: 'distinct-1' } as any,
            })

            const result = await hogInputsService.buildInputsWithGlobals(hogFunction, globals)

            expect(pushSubscriptionsManager.deactivateSubscriptionsByIds).not.toHaveBeenCalled()
            expect(result.push_subscriptions).toEqual([{ id: 'sub-1' }, { id: 'sub-2' }])
        })

        it('does not disable subscriptions when PersonDistinctId query returns no results', async () => {
            const mockSubscriptions = [
                {
                    id: 'sub-1',
                    team_id: team.id,
                    distinct_id: 'distinct-1',
                    token: 'token-1',
                    token_hash: 'hash-1',
                    platform: 'android' as const,
                    is_active: true,
                    last_successfully_used_at: null,
                    created_at: '2025-01-01T00:00:00Z',
                    updated_at: '2025-01-01T00:00:00Z',
                    person_id: null,
                },
            ]

            jest.spyOn(pushSubscriptionsManager, 'get').mockResolvedValue(mockSubscriptions)
            jest.spyOn(pushSubscriptionsManager, 'updatePersonIds').mockResolvedValue(undefined)
            jest.spyOn(pushSubscriptionsManager, 'deactivateSubscriptionsByIds').mockResolvedValue(undefined)
            jest.spyOn(hub.postgres, 'query').mockResolvedValue({ rows: [] } as any)

            const hogFunction = createHogFunction({
                team_id: team.id,
                inputs_schema: [{ key: 'push_sub', type: 'push_subscription', required: true }],
            })

            const globals = createHogExecutionGlobals({
                event: { distinct_id: 'distinct-1' } as any,
            })

            const result = await hogInputsService.buildInputsWithGlobals(hogFunction, globals)

            expect(pushSubscriptionsManager.updatePersonIds).not.toHaveBeenCalled()
            expect(pushSubscriptionsManager.deactivateSubscriptionsByIds).not.toHaveBeenCalled()
            // Subscription without person_id should still be included (grouped as 'null:hash-1')
            expect(result.push_subscriptions).toEqual([{ id: 'sub-1' }])
        })
    })
})
