import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { HogFlowAction } from '../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { RecipientPreferencesService } from './recipient-preferences.service'

describe('RecipientPreferencesService', () => {
    let hub: Hub
    let team: Team
    let service: RecipientPreferencesService
    let mockRecipientsManager: RecipientsManagerService
    let mockRecipientsManagerGet: jest.SpyInstance
    let mockRecipientsManagerGetPreference: jest.SpyInstance

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        mockRecipientsManager = new RecipientsManagerService(hub)
        mockRecipientsManagerGet = jest.spyOn(mockRecipientsManager, 'get')
        mockRecipientsManagerGetPreference = jest.spyOn(mockRecipientsManager, 'getPreference')

        service = new RecipientPreferencesService(mockRecipientsManager)
    })

    afterEach(async () => {
        jest.restoreAllMocks()
        await closeHub(hub)
    })

    const createRecipient = (identifier: string, preferences: Record<string, string> = {}) => ({
        id: 'recipient-1',
        team_id: team.id,
        identifier,
        preferences,
        created_at: '2023-01-01T00:00:00Z',
        updated_at: '2023-01-01T00:00:00Z',
    })

    const createInvocation = (action: HogFlowAction): CyclotronJobInvocationHogFlow => {
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

        return createExampleHogFlowInvocation(hogFlow)
    }

    describe('shouldSkipAction', () => {
        describe('for email actions', () => {
            const createEmailAction = (
                to: string = 'test@example.com',
                categoryId?: string
            ): Extract<HogFlowAction, { type: 'function_email' }> => ({
                id: 'email',
                type: 'function_email',
                config: {
                    template_id: 'template-email',
                    message_category_id: categoryId,
                    inputs: {
                        email: {
                            value: { to },
                        },
                    },
                },
            })

            it('should return true if recipient is opted out for the specific category', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_OUT')

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

            it('should return true if recipient is opted out for $all category when no category is specified', async () => {
                const action = createEmailAction('test@example.com')
                const invocation = createInvocation(action)
                const recipient = createRecipient('test@example.com', { $all: 'OPTED_OUT' })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_OUT')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(true)
                expect(mockRecipientsManagerGetPreference).toHaveBeenCalledWith(recipient, '$all')
            })

            it('should return false if recipient is opted in', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createInvocation(action)
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_IN')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
            })

            it('should return false if recipient has no preference', async () => {
                const action = createEmailAction('test@example.com', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createInvocation(action)
                const recipient = createRecipient('test@example.com', {})

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('NO_PREFERENCE')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
            })

            it('should return false if recipient is not found', async () => {
                const action = createEmailAction('test@example.com')
                const invocation = createInvocation(action)

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
                const action = createEmailAction('test@example.com')
                const invocation = createInvocation(action)
                const consoleSpy = jest.spyOn(console, 'error').mockImplementation()

                mockRecipientsManagerGet.mockRejectedValue(new Error('Database error'))

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
                expect(consoleSpy).toHaveBeenCalledWith(
                    'Failed to fetch recipient preferences for test@example.com:',
                    expect.any(Error)
                )

                consoleSpy.mockRestore()
            })

            it('should throw error if no email identifier is found', async () => {
                const action: Extract<HogFlowAction, { type: 'function_email' }> = {
                    id: 'email',
                    type: 'function_email',
                    config: {
                        template_id: 'template-email',
                        inputs: {
                            email: {
                                value: {},
                            },
                        },
                    },
                }
                const invocation = createInvocation(action)

                await expect(service.shouldSkipAction(invocation, action)).rejects.toThrow(
                    'No identifier found for message action email'
                )
            })
        })

        describe('for SMS actions', () => {
            const createSmsAction = (
                toNumber: string = '+1234567890',
                categoryId?: string
            ): Extract<HogFlowAction, { type: 'function_sms' }> => ({
                id: 'sms',
                type: 'function_sms',
                config: {
                    template_id: 'template-sms',
                    message_category_id: categoryId,
                    inputs: {
                        to_number: toNumber,
                    },
                },
            })

            it('should return true if SMS recipient is opted out', async () => {
                const action = createSmsAction('+1234567890', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createInvocation(action)
                const recipient = createRecipient('+1234567890', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_OUT')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(true)
                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: '+1234567890',
                })
            })

            it('should return false if SMS recipient is opted in', async () => {
                const action = createSmsAction('+1234567890', '123e4567-e89b-12d3-a456-426614174000')
                const invocation = createInvocation(action)
                const recipient = createRecipient('+1234567890', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN',
                })

                mockRecipientsManagerGet.mockResolvedValue(recipient)
                mockRecipientsManagerGetPreference.mockReturnValue('OPTED_IN')

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
            })

            it('should throw error if no SMS identifier is found', async () => {
                const action: Extract<HogFlowAction, { type: 'function_sms' }> = {
                    id: 'sms',
                    type: 'function_sms',
                    config: {
                        template_id: 'template-sms',
                        inputs: {},
                    },
                }
                const invocation = createInvocation(action)

                await expect(service.shouldSkipAction(invocation, action)).rejects.toThrow(
                    'No identifier found for message action sms'
                )
            })
        })

        describe('for other action types', () => {
            it('should return false for function actions', async () => {
                const action: Extract<HogFlowAction, { type: 'function' }> = {
                    id: 'function',
                    type: 'function',
                    config: {
                        template_id: 'template-function',
                        inputs: {},
                    },
                }
                const invocation = createInvocation(action)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })

            it('should return false for function_slack actions', async () => {
                const action: Extract<HogFlowAction, { type: 'function_slack' }> = {
                    id: 'slack',
                    type: 'function_slack',
                    config: {
                        template_id: 'template-slack',
                        inputs: {},
                    },
                }
                const invocation = createInvocation(action)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })

            it('should return false for function_webhook actions', async () => {
                const action: Extract<HogFlowAction, { type: 'function_webhook' }> = {
                    id: 'webhook',
                    type: 'function_webhook',
                    config: {
                        template_id: 'template-webhook',
                        inputs: {},
                    },
                }
                const invocation = createInvocation(action)

                const result = await service.shouldSkipAction(invocation, action)

                expect(result).toBe(false)
                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })
        })
    })
})
