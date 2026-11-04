import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleInvocation } from '~/cdp/_tests/fixtures'
import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { defaultConfig } from '~/common/config/config'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisV2 } from '~/common/redis/redis-v2'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { UUIDT } from '~/common/utils/utils'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { FrequencyCap, TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { EmailSuppressionService, emailSuppressionConfigFromEnv } from './email-suppression.service'
import { createFrequencyCapValkeyPool } from './frequency-cap-valkey-pool'
import {
    FrequencyCapCheck,
    FrequencyCapHoldOptions,
    RecipientPreferencesService,
} from './recipient-preferences.service'
import { RecipientTokensService } from './recipient-tokens.service'

const escapeRegExp = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

describe('RecipientPreferencesService', () => {
    let hub: Hub
    let team: Team
    let service: RecipientPreferencesService
    let mockRecipientsManager: RecipientsManagerService
    let mockEmailSuppressionService: EmailSuppressionService
    let mockRecipientsManagerGet: jest.SpyInstance
    let mockRecipientsManagerGetPreference: jest.SpyInstance
    let mockRecipientsManagerGetAllMarketingMessagingPreference: jest.SpyInstance

    beforeEach(async () => {
        hub = await createHub()
        team = (await createTestTeamFixture(hub.postgres)).team
        mockRecipientsManager = new RecipientsManagerService(hub.postgres)
        mockRecipientsManagerGet = jest.spyOn(mockRecipientsManager, 'get')
        mockRecipientsManagerGetPreference = jest.spyOn(mockRecipientsManager, 'getPreference')
        mockRecipientsManagerGetAllMarketingMessagingPreference = jest.spyOn(
            mockRecipientsManager,
            'getAllMarketingMessagingPreference'
        )

        mockEmailSuppressionService = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
        service = new RecipientPreferencesService(mockRecipientsManager, mockEmailSuppressionService)
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await closeHub(hub)
    })

    const createRecipient = (
        identifier: string,
        preferences: Record<string, string> = {}
    ): {
        id: string
        team_id: number
        identifier: string
        preferences: Record<string, string>
        created_at: string
        updated_at: string
    } => ({
        id: new UUIDT().toString(),
        team_id: team.id,
        identifier,
        preferences,
        created_at: '2023-01-01T00:00:00Z',
        updated_at: '2023-01-01T00:00:00Z',
    })

    const createFunctionStepInvocation = (
        action: Extract<HogFlowAction, { type: 'function' | 'function_email' | 'function_sms' | 'function_push' }>
    ): CyclotronJobInvocationHogFunction => {
        const hogFlow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withWorkflow({
                actions: {
                    test: action,
                    exit: {
                        type: 'exit',
                        config: {},
                    },
                },
                edges: [
                    {
                        from: 'test',
                        to: 'exit',
                        type: 'continue',
                    },
                ],
            })
            .build()

        // Hacky but we just want to test the service, so we'll add the inputs to the invocation
        const inputs = Object.entries(action.config.inputs).reduce(
            (acc, [key, value]) => {
                acc[key] = value.value
                return acc
            },
            {} as Record<string, any>
        )

        // HogFlow only overlaps HogFunctionType structurally; updated_at diverges (Date|number vs string)
        return createExampleInvocation(hogFlow as unknown as Parameters<typeof createExampleInvocation>[0], {
            inputs,
        })
    }

    describe('shouldSkipAction', () => {
        describe('for email actions', () => {
            const createEmailAction = (
                to: string = 'test@example.com',
                categoryId: string,
                categoryType?: 'marketing' | 'transactional'
            ): Extract<HogFlowAction, { type: 'function_email' }> => ({
                id: 'email',
                name: 'Send email',
                description: 'Send an email to the recipient',
                type: 'function_email',
                filters: null,
                config: {
                    template_id: 'template-email',
                    message_category_id: categoryId,
                    message_category_type: categoryType,
                    inputs: {
                        email: {
                            value: {
                                to: {
                                    email: to,
                                },
                                from: {
                                    integrationId: 1,
                                },
                                subject: 'Test Subject',
                                text: 'Test Text',
                                html: 'Test HTML',
                            },
                        },
                    },
                },
                created_at: Date.now(),
                updated_at: Date.now(),
            })

            it('should return true if recipient is opted out for the specific category', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_OUT')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe('opted_out')
                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: 'test@example.com',
                })
                expect(mockRecipientsManagerGetPreference).toHaveBeenCalledWith(
                    recipient,
                    '123e4567-e89b-12d3-a456-426614174000'
                )
            })

            it.each([
                ['the same category', '123e4567-e89b-12d3-a456-426614174000', 'opted_out'],
                ['all marketing', '$all', 'opted_out'],
                ['another category', '00000000-0000-4000-8000-000000000000', null],
            ])('uses an opt-out this run made for %s before the cache', async (_name, categoryId, expected) => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                mockRecipientsManagerGet.mockResolvedValue(null)

                const result = await service.shouldSkipAction(invocation, action, [
                    { identifier: 'test@example.com', categoryId },
                ])

                expect(result).toBe(expected)
            })

            it('should return false if recipient is opted in', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_IN')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
            })

            it('should return false if recipient has no preference', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {})

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('NO_PREFERENCE')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
            })

            it('should return false if recipient is not found', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)

                mockRecipientsManagerGet.mockResolvedValue(null)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: 'test@example.com',
                })
                expect(mockRecipientsManagerGetPreference).not.toHaveBeenCalled()
            })

            it('should handle errors gracefully and return false', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const loggerSpy = jest.spyOn(logger, 'error').mockImplementation()

                mockRecipientsManagerGet.mockRejectedValue(new Error('Database error'))

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
                expect(loggerSpy).toHaveBeenCalledWith(
                    'Failed to fetch recipient preferences for test@example.com:',
                    expect.any(Error)
                )

                loggerSpy.mockRestore()
            })

            it('should not skip when no email identifier is found, so the send records the missing recipient', async () => {
                const action = createEmailAction('', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)

                await expect(service.shouldSkipAction(invocation, action)).resolves.toBeNull()
                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })

            it.each([
                ['an existing category', '123e4567-e89b-12d3-a456-426614174000'],
                ['no category', ''],
                ['a category created after the opt-out', '123e4567-e89b-12d3-a456-426614174001'],
            ])('should block globally opted-out recipients for %s', async (_name, categoryId) => {
                const action = createEmailAction('test@example.com', categoryId)
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN', // Opted in for this category
                    $all: 'OPTED_OUT', // But opted out of all marketing
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe('opted_out')
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })

            it.each([
                ['the specific category', { '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT' }],
                ['all marketing messaging', { $all: 'OPTED_OUT' }],
            ])(
                'should return false for a transactional email even when recipient is opted out of %s',
                async (_label, preferences) => {
                    const action = createEmailAction(
                        'test@example.com',
                        '123e4567-e89b-12d3-a456-426614174000',
                        'transactional'
                    )
                    const invocation = createFunctionStepInvocation(action)

                    mockRecipientsManagerGet.mockResolvedValue(createRecipient('test@example.com', preferences))

                    const result = await service.shouldSkipAction(invocation, action)

                    expect(result).toBeNull()
                    // Transactional messages bypass the opt-out lookup entirely
                    expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
                }
            )

            it('should return true if recipient is opted out of specific category even when opted in to all marketing', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT', // Opted out for this category
                    $all: 'OPTED_IN', // But opted in for all marketing
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_OUT')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('OPTED_IN')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe('opted_out')
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })

            it('should return false if recipient is opted in to both specific category and all marketing', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN',
                    $all: 'OPTED_IN',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_IN')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('OPTED_IN')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })

            it('should return false if recipient has no preference for category but is opted in to all marketing', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    $all: 'OPTED_IN',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('NO_PREFERENCE')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('OPTED_IN')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })

            it('should return false if recipient has no preference for either category or all marketing', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {})

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('NO_PREFERENCE')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })

            describe('when the recipient is on the suppression list', () => {
                // A hard bounce must block even transactional messages, ahead of the transactional
                // opt-out bypass. Soft bounces alone must not.
                const insertSuppressionRow = async (email: string, hardBounced = false): Promise<void> => {
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        `INSERT INTO posthog_messagesuppression
                            (id, team_id, identifier, source, reason, transient_bounce_count,
                             suppressed, suppressed_at, deleted, created_at, updated_at, hard_bounced_at)
                         VALUES (gen_random_uuid(), $1, $2, 'BOUNCE', 'test row', 5,
                             true, NOW(), false, NOW(), NOW(), CASE WHEN $3 THEN NOW() END)`,
                        [team.id, email, hardBounced],
                        'test-insert-suppression'
                    )
                }

                it.each([
                    ['skips a marketing email after soft bounces', 'marketing' as const, false, 'suppressed'],
                    ['sends a transactional email after soft bounces', 'transactional' as const, false, null],
                    ['skips a transactional email after a hard bounce', 'transactional' as const, true, 'suppressed'],
                ])('%s', async (_label, categoryType, hardBounced, expected) => {
                    const email = `suppressed-${categoryType}-${hardBounced}@example.com`
                    await insertSuppressionRow(email, hardBounced)
                    const action = createEmailAction(email, '123e4567-e89b-12d3-a456-426614174000', categoryType)
                    const invocation = createFunctionStepInvocation(action)

                    const result = await service.shouldSkipAction(invocation, action)

                    expect(result).toBe(expected)
                })

                // Suppressed cc and bcc addresses are removed at send time, and a deliverable cc address
                // replaces a suppressed `to`. The step is skipped only when no cc address is left.
                it.each([
                    ['a suppressed cc', 'legit-to@example.com', { cc: 'suppressed-cc@example.com' }, {}, null],
                    ['a suppressed bcc', 'legit-to@example.com', { bcc: 'suppressed-bcc@example.com' }, {}, null],
                    [
                        'a suppressed to with a deliverable cc',
                        'suppressed-to@example.com',
                        { cc: 'ok@example.com' },
                        {},
                        null,
                    ],
                    [
                        'a suppressed to with only bcc left',
                        'suppressed-to@example.com',
                        { bcc: 'ok@example.com' },
                        {},
                        'suppressed',
                    ],
                    [
                        "a suppressed to with a code send's deliverable cc",
                        'suppressed-to@example.com',
                        {},
                        { cc: ['ok@example.com'] },
                        null,
                    ],
                    [
                        "a suppressed to with only a code send's bcc left",
                        'suppressed-to@example.com',
                        {},
                        { bcc: ['ok@example.com'] },
                        'suppressed',
                    ],
                ] as const)('handles %s', async (_label, to, extraInputs, copies, expected) => {
                    await insertSuppressionRow('suppressed-cc@example.com')
                    await insertSuppressionRow('suppressed-bcc@example.com')
                    await insertSuppressionRow('suppressed-to@example.com')
                    const action = createEmailAction(to, '123e4567-e89b-12d3-a456-426614174000', 'marketing')
                    const invocation = createFunctionStepInvocation(action)
                    // Inject the cc/bcc into the resolved invocation inputs (this is what the
                    // executor sees at send time after template resolution).
                    Object.assign(invocation.state.globals!.inputs!.email as object, extraInputs)
                    invocation.state.send = { tracking: { captureEngagement: false }, ...copies }
                    mockRecipientsManagerGet.mockResolvedValue(null)

                    const result = await service.shouldSkipAction(invocation, action)

                    expect(result).toBe(expected)
                })
            })
        })

        describe('for SMS actions', () => {
            const createSmsAction = (
                toNumber: string = '+1234567890',
                categoryId: string
            ): Extract<HogFlowAction, { type: 'function_sms' }> => ({
                id: 'sms',
                name: 'Send SMS',
                description: 'Send an SMS to the recipient',
                type: 'function_sms',
                filters: null,
                config: {
                    template_id: 'template-twilio',
                    message_category_id: categoryId,
                    inputs: {
                        to_number: { value: toNumber },
                    },
                },
                created_at: Date.now(),
                updated_at: Date.now(),
            })

            it('should return true if SMS recipient is opted out', async () => {
                const action = createSmsAction('+1234567890', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('+1234567890', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_OUT')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe('opted_out')
                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: '+1234567890',
                })
            })

            it('should return false if SMS recipient is opted in', async () => {
                const action = createSmsAction('+1234567890', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('+1234567890', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_IN')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
            })

            it('should throw error if no SMS identifier is found', async () => {
                const action = createSmsAction('', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)

                await expect(service.shouldSkipAction(invocation, action)).rejects.toThrow(
                    `No recipient identifier found for message action [Action:${action.id}]. Check that the message 'to' field is set correctly for this person.`
                )
            })

            it('should return true if SMS recipient is opted out of all marketing messaging', async () => {
                const action = createSmsAction('+1234567890', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('+1234567890', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN', // Opted in for this category
                    $all: 'OPTED_OUT', // But opted out of all marketing
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_IN')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('OPTED_OUT')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe('opted_out')
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })

            it('should return false if SMS recipient is opted in to both specific category and all marketing', async () => {
                const action = createSmsAction('+1234567890', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('+1234567890', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN',
                    $all: 'OPTED_IN',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_IN')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('OPTED_IN')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })
        })

        describe('for push actions', () => {
            const createPushAction = (
                categoryId: string,
                categoryType?: 'marketing' | 'transactional'
            ): Extract<HogFlowAction, { type: 'function_push' }> => ({
                id: 'push',
                name: 'Send push',
                description: 'Send a push notification to the recipient',
                type: 'function_push',
                filters: null,
                config: {
                    template_id: 'template-native-push',
                    message_category_id: categoryId,
                    message_category_type: categoryType,
                    inputs: {},
                },
                created_at: Date.now(),
                updated_at: Date.now(),
            })

            // Push is keyed by the recipient's distinct_id (from the triggering event), not an email/phone
            // 'to' field — that is the identifier the device token was registered under.
            it.each([
                ['opted out', 'OPTED_OUT', 'opted_out'],
                ['opted in', 'OPTED_IN', null],
            ] as const)(
                'marketing push to a recipient %s of the category → skipReason=%s',
                async (_label, status, expectedReason) => {
                    const action = createPushAction('123e4567-e89b-12d3-a456-426614174000', 'marketing')
                    const invocation = createFunctionStepInvocation(action)
                    const recipient = createRecipient('distinct_id', {
                        '123e4567-e89b-12d3-a456-426614174000': status,
                    })

                    mockRecipientsManagerGet.mockResolvedValue(recipient)
                    mockRecipientsManagerGetPreference.mockReturnValue(status)
                    mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                    const result = await service.shouldSkipAction(invocation, action)

                    expect(result).toBe(expectedReason)
                    expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                        teamId: team.id,
                        identifier: 'distinct_id',
                    })
                }
            )

            it('should return false for a transactional push without checking preferences', async () => {
                const action = createPushAction('123e4567-e89b-12d3-a456-426614174000', 'transactional')
                const invocation = createFunctionStepInvocation(action)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })

            it.each([
                ['no Distinct ID input', undefined, 'delivered-person', 'function_push'],
                ['the run event distinct_id', 'trigger-person', 'delivered-person', 'function_push'],
                ['another person', ' named-user ', 'named-user', 'function_push'],
                [
                    'another person, from a generic function step on the push template',
                    'named-user',
                    'named-user',
                    'function',
                ],
            ] as const)(
                'keys the opt-out on the person the push is delivered to, for %s',
                async (_, distinctIdInput, expected, stepType) => {
                    const pushAction = createPushAction('123e4567-e89b-12d3-a456-426614174000', 'marketing')
                    const action = (stepType === 'function' ? { ...pushAction, type: 'function' } : pushAction) as any
                    const invocation = createFunctionStepInvocation(action)
                    invocation.state.globals.person!.distinct_id = 'delivered-person'
                    invocation.state.globals.event!.distinct_id = 'trigger-person'
                    invocation.state.globals.inputs.distinctId = distinctIdInput

                    mockRecipientsManagerGet.mockResolvedValue(
                        createRecipient(expected, {
                            '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT',
                        })
                    )
                    mockRecipientsManagerGetPreference.mockReturnValue('OPTED_OUT')
                    mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                    const result = await service.shouldSkipAction(invocation, action)

                    expect(result).toBe('opted_out')
                    expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                        teamId: team.id,
                        identifier: expected,
                    })
                }
            )
        })

        describe('for other action types', () => {
            it('should return false for function actions', async () => {
                const action: Extract<HogFlowAction, { type: 'function' }> = {
                    id: 'function',
                    name: 'Execute function',
                    description: 'Execute a custom hog function',
                    type: 'function',
                    filters: null,
                    config: {
                        template_id: 'template-function',
                        inputs: {},
                    },
                    created_at: Date.now(),
                    updated_at: Date.now(),
                }
                const invocation = createFunctionStepInvocation(action)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBeNull()
                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })
        })
    })

    describe('checkFrequencyCap', () => {
        let valkey: RedisV2
        let frequencyCap: FrequencyCap
        let teamWorkflowsConfig: TeamWorkflowsConfigService
        let cappedService: RecipientPreferencesService
        let persons: { getCyclotronPerson: jest.Mock }

        const emailAction = (
            categoryType?: 'marketing' | 'transactional',
            skipFrequencyCap?: boolean
        ): Extract<HogFlowAction, { type: 'function_email' }> => ({
            id: 'email',
            name: 'Send email',
            description: '',
            type: 'function_email',
            filters: null,
            config: {
                template_id: 'template-email',
                message_category_type: categoryType,
                skip_frequency_cap: skipFrequencyCap,
                inputs: { email: { value: { to: { email: 'capped@example.com' } } } },
            },
            created_at: Date.now(),
            updated_at: Date.now(),
        })

        beforeAll(() => {
            // One pool for the block: RedisV2 has no close, so a pool per test would leave its connections open.
            valkey = createFrequencyCapValkeyPool(defaultConfig)!
        })

        beforeEach(async () => {
            await deleteKeysWithPrefix(valkey, `@posthog/workflows-frequency-cap/${team.id}/`)
            frequencyCap = { max_messages: 2, window_days: 7, hold_hours: null }
            teamWorkflowsConfig = new TeamWorkflowsConfigService(hub.postgres, hub.pubSub)
            jest.spyOn(teamWorkflowsConfig, 'getFrequencyCap').mockImplementation(() => Promise.resolve(frequencyCap))
            persons = { getCyclotronPerson: jest.fn().mockResolvedValue(null) }
            cappedService = new RecipientPreferencesService(mockRecipientsManager, mockEmailSuppressionService, {
                teamWorkflowsConfig,
                valkey,
                persons,
            })
        })

        const checkAt = async (action: HogFlowAction, at: number): Promise<FrequencyCapCheck> => {
            jest.spyOn(Date, 'now').mockReturnValue(at)
            return cappedService.checkFrequencyCap(createFunctionStepInvocation(action as any), action)
        }
        const sendAt = async (action: HogFlowAction, at: number): Promise<boolean> => (await checkAt(action, at)).capped

        it('caps marketing sends past the limit until the window moves past the oldest send', async () => {
            const day = 24 * 60 * 60 * 1000
            const start = 1_800_000_000_000

            expect(await sendAt(emailAction(), start)).toBe(false)
            expect(await sendAt(emailAction(), start + day)).toBe(false)
            expect(await checkAt(emailAction(), start + 2 * day)).toEqual({
                capped: true,
                nextSlotAt: start + 7 * day,
                hold: null,
            })
            expect(await sendAt(emailAction(), start + 7 * day + 1)).toBe(false)
        })

        it('lets a re-entered step visit keep its slot from the send time and counts a later visit', async () => {
            frequencyCap = { max_messages: 1, window_days: 1, hold_hours: 12 }
            const hour = 60 * 60 * 1000
            const start = 1_800_000_000_000
            const action = emailAction()
            const invocation = createFunctionStepInvocation(action)
            invocation.state.actionId = action.id
            invocation.state.actionStepCount = 1
            const visitAt = async (at: number): Promise<FrequencyCapCheck> => {
                jest.spyOn(Date, 'now').mockReturnValue(at)
                return cappedService.checkFrequencyCap(invocation, action)
            }

            // The email queue runs the step a second time after the hog queue routed it there and paced it.
            expect(await visitAt(start)).toEqual({ capped: false })
            expect(await visitAt(start + 23 * hour)).toEqual({ capped: false })

            // The slot frees a day after the second run moved it, not a day after the first check.
            invocation.state.actionStepCount = 3
            expect(await visitAt(start + 25 * hour)).toEqual({
                capped: true,
                nextSlotAt: start + 47 * hour,
                hold: null,
            })
        })

        describe('held sends', () => {
            const day = 24 * 60 * 60 * 1000
            const start = 1_800_000_000_000
            const action = emailAction()
            const checkHeld = async (
                invocation: CyclotronJobInvocationHogFunction,
                at: number,
                hold: FrequencyCapHoldOptions = { canHold: true }
            ): Promise<FrequencyCapCheck> => {
                jest.spyOn(Date, 'now').mockReturnValue(at)
                return cappedService.checkFrequencyCap(invocation, action, hold)
            }
            const heldUntil = (deadlineAt: number): FrequencyCapHoldOptions => ({
                canHold: true,
                deadlineAt: new Date(deadlineAt).toISOString(),
            })

            it('gives a freed slot to held sends in the order they were capped', async () => {
                frequencyCap = { max_messages: 1, window_days: 1, hold_hours: 48 }
                const [first, second, tooLate, fresh] = [1, 2, 3, 4].map(() => createFunctionStepInvocation(action))

                expect(await sendAt(emailAction(), start)).toBe(false)
                expect(await checkHeld(first, start + 1)).toMatchObject({
                    capped: true,
                    nextSlotAt: start + day,
                    hold: { deadlineAt: start + 1 + 2 * day },
                })
                expect(await checkHeld(second, start + 2)).toMatchObject({
                    capped: true,
                    nextSlotAt: start + 2 * day,
                    hold: { deadlineAt: start + 2 + 2 * day },
                })
                // Its slot frees after its hold would end, so it skips and does not join the line.
                expect(await checkHeld(tooLate, start + 3)).toMatchObject({ capped: true, hold: null })

                // The slot frees before the held sends wake. A new send waits behind both of them.
                expect(await checkHeld(fresh, start + day + 1, { canHold: false })).toEqual({
                    capped: true,
                    nextSlotAt: start + 3 * day + 1,
                    hold: null,
                })
                expect(await checkHeld(second, start + day + 1, heldUntil(start + 2 + 2 * day))).toMatchObject({
                    capped: true,
                    nextSlotAt: start + 2 * day + 1,
                })
                expect(await checkHeld(first, start + day + 1, heldUntil(start + 1 + 2 * day))).toEqual({
                    capped: false,
                })
            })

            it.each([
                ['is released', 48, start + day + 1, true],
                ['passes its deadline', 30, start + 1 + 30 * 60 * 60 * 1000, false],
            ])('lets the next held send take the slot when the send ahead %s', async (_, holdHours, at, release) => {
                frequencyCap = { max_messages: 1, window_days: 1, hold_hours: holdHours }
                const [first, second] = [1, 2].map(() => createFunctionStepInvocation(action))

                expect(await sendAt(emailAction(), start)).toBe(false)
                const firstCheck = await checkHeld(first, start + 1)
                await checkHeld(second, start + 2)
                if (release && firstCheck.capped && firstCheck.hold) {
                    await cappedService.releaseFrequencyCapHold(team.id, firstCheck.hold.line)
                }

                expect(await checkHeld(second, at, heldUntil(start + 2 + holdHours * 60 * 60 * 1000))).toEqual({
                    capped: false,
                })
            })
        })

        it('counts a push to a named person against that person, not the run person', async () => {
            frequencyCap = { max_messages: 1, window_days: 7, hold_hours: null }
            persons.getCyclotronPerson.mockResolvedValue({ id: 'named-person-id' })
            const pushToNamed: Extract<HogFlowAction, { type: 'function_push' }> = {
                id: 'push',
                name: 'Send push',
                description: '',
                type: 'function_push',
                filters: null,
                config: { template_id: 'template-native-push', inputs: { distinctId: { value: 'named-user' } } },
                created_at: Date.now(),
                updated_at: Date.now(),
            }

            expect(await sendAt(pushToNamed, 1_800_000_000_000)).toBe(false)
            expect(await sendAt(pushToNamed, 1_800_000_000_001)).toBe(true)
            expect(persons.getCyclotronPerson).toHaveBeenCalledWith(team.id, 'named-user', 'distinct_id')
            expect(await sendAt(emailAction(), 1_800_000_000_002)).toBe(false)
        })

        it.each([
            [
                'the config lookup',
                () => jest.spyOn(teamWorkflowsConfig, 'getFrequencyCap').mockRejectedValue(new Error('unavailable')),
            ],
            ['the Valkey pool', () => jest.spyOn(valkey, 'useClient').mockRejectedValue(new Error('unavailable'))],
        ])('lets the send through when %s fails', async (_, fail) => {
            fail()
            expect(await sendAt(emailAction(), 1_800_000_000_000)).toBe(false)
        })

        it.each([
            [
                'transactional sends',
                emailAction('transactional'),
                { max_messages: 0, window_days: 7, hold_hours: null },
            ],
            [
                'marketing sends that skip the cap',
                emailAction('marketing', true),
                { max_messages: 1, window_days: 7, hold_hours: null },
            ],
            ['teams with no cap', emailAction(), { max_messages: null, window_days: null, hold_hours: null }],
        ])('never caps %s', async (_, action, cap) => {
            frequencyCap = cap
            for (let i = 0; i < 3; i++) {
                expect(await sendAt(action, 1_800_000_000_000 + i)).toBe(false)
            }
        })
    })

    describe('recipient token URLs', () => {
        let tokensService: RecipientTokensService

        beforeEach(() => {
            tokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        })

        it('should generate a preferences URL with a trailing slash', () => {
            const url = tokensService.generatePreferencesUrl({ team_id: team.id, identifier: 'test@example.com' })

            expect(url).toMatch(new RegExp(`^${escapeRegExp(hub.SITE_URL)}/messaging-preferences/[^/]+/$`))
        })

        it('should generate a one-click unsubscribe URL with the query param', () => {
            const url = tokensService.generateOneClickUnsubscribeUrl({
                team_id: team.id,
                identifier: 'test@example.com',
            })

            expect(url).toMatch(
                new RegExp(`^${escapeRegExp(hub.SITE_URL)}/messaging-preferences/[^/]+/\\?one_click_unsubscribe=1$`)
            )
        })
    })
})
