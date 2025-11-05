import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleInvocation } from '~/cdp/_tests/fixtures'
import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { logger } from '~/utils/logger'
import { UUIDT } from '~/utils/utils'

import { HogFlowAction } from '../../../schema/hogflow'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { RecipientPreferencesService } from './recipient-preferences.service'

describe('RecipientPreferencesService', () => {
    let hub: Hub
    let team: Team
    let service: RecipientPreferencesService
    let mockRecipientsManager: RecipientsManagerService
    let mockRecipientsManagerGet: jest.SpyInstance
    let mockRecipientsManagerGetPreference: jest.SpyInstance
    let mockRecipientsManagerGetAllMarketingMessagingPreference: jest.SpyInstance

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        mockRecipientsManager = new RecipientsManagerService(hub)
        mockRecipientsManagerGet = jest.spyOn(mockRecipientsManager, 'get')
        mockRecipientsManagerGetPreference = jest.spyOn(mockRecipientsManager, 'getPreference')
        mockRecipientsManagerGetAllMarketingMessagingPreference = jest.spyOn(
            mockRecipientsManager,
            'getAllMarketingMessagingPreference'
        )

        service = new RecipientPreferencesService(mockRecipientsManager)
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
        action: Extract<HogFlowAction, { type: 'function' | 'function_email' | 'function_sms' }>
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

        return createExampleInvocation(hogFlow, { inputs })
    }

    describe('shouldSkipAction', () => {
        describe('for email actions', () => {
            const createEmailAction = (
                to: string = 'test@example.com',
                categoryId: string
            ): Extract<HogFlowAction, { type: 'function_email' }> => ({
                id: 'email',
                name: 'Send email',
                description: 'Send an email to the recipient',
                type: 'function_email',
                config: {
                    template_id: 'template-email',
                    message_category_id: categoryId,
                    inputs: {
                        email: {
                            value: {
                                to: {
                                    email: to,
                                },
                                from: {
                                    email: 'from@example.com',
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

                expect(result).toBe(true)
                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: 'test@example.com',
                })
                expect(mockRecipientsManagerGetPreference).toHaveBeenCalledWith(
                    recipient,
                    '123e4567-e89b-12d3-a456-426614174000'
                )
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

                expect(result).toBe(false)
            })

            it('should return false if recipient has no preference', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {})

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('NO_PREFERENCE')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('NO_PREFERENCE')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
            })

            it('should return false if recipient is not found', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)

                mockRecipientsManagerGet.mockResolvedValue(null)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
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

                expect(result).toBe(false)
                expect(loggerSpy).toHaveBeenCalledWith(
                    'Failed to fetch recipient preferences for test@example.com:',
                    expect.any(Error)
                )

                loggerSpy.mockRestore()
            })

            it('should throw error if no email identifier is found', async () => {
                const action = createEmailAction('', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)

                await expect(service.shouldSkipAction(invocation, action)).rejects.toThrow(
                    'No identifier found for message action email'
                )
            })

            it('should return true if recipient is opted out of all marketing messaging', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN', // Opted in for this category
                    $all: 'OPTED_OUT', // But opted out of all marketing
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_IN')
                mockRecipientsManagerGetAllMarketingMessagingPreference.mockReturnValue('OPTED_OUT')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(true)
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })

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

                expect(result).toBe(true)
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

                expect(result).toBe(false)
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

                expect(result).toBe(false)
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

                expect(result).toBe(false)
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
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

                expect(result).toBe(true)
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

                expect(result).toBe(false)
            })

            it('should throw error if no SMS identifier is found', async () => {
                const action = createSmsAction('', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createFunctionStepInvocation(action)

                await expect(service.shouldSkipAction(invocation, action)).rejects.toThrow(
                    'No identifier found for message action sms'
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

                expect(result).toBe(true)
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

                expect(result).toBe(false)
                expect(mockRecipientsManagerGetAllMarketingMessagingPreference).toHaveBeenCalledWith(recipient)
            })
        })

        describe('for other action types', () => {
            it('should return false for function actions', async () => {
                const action: Extract<HogFlowAction, { type: 'function' }> = {
                    id: 'function',
                    name: 'Execute function',
                    description: 'Execute a custom hog function',
                    type: 'function',
                    config: {
                        template_id: 'template-function',
                        inputs: {},
                    },
                    created_at: Date.now(),
                    updated_at: Date.now(),
                }
                const invocation = createFunctionStepInvocation(action)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })
        })
    })
})
