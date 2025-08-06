// eslint-disable-next-line simple-import-sort/imports
import { mockFetch } from '~/tests/helpers/mocks/request.mock'
import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { compileHog } from '~/cdp/templates/compiler'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { HogFlowAction } from '../../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../../types'
import { HogExecutorService } from '../../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../../managers/hog-function-template-manager.service'
import { RecipientsManagerService } from '../../managers/recipients-manager.service'
import { findActionByType } from '../hogflow-utils'
import { HogFunctionHandler } from './hog_function'

describe('HogFunctionHandler', () => {
    let hub: Hub
    let team: Team
    let hogFunctionHandler: HogFunctionHandler
    let mockHogFunctionExecutor: HogExecutorService
    let mockHogFunctionTemplateManager: HogFunctionTemplateManagerService
    let mockRecipientsManager: RecipientsManagerService

    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'function' }>

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        mockHogFunctionExecutor = new HogExecutorService(hub)
        mockHogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub)
        mockRecipientsManager = new RecipientsManagerService(hub)
        hogFunctionHandler = new HogFunctionHandler(
            hub,
            mockHogFunctionExecutor,
            mockHogFunctionTemplateManager,
            mockRecipientsManager
        )

        // Simple hog function that prints the inputs
        const exampleHog = `fetch('http://localhost/test', { 'method': 'POST', 'body': inputs })`

        const template = await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-test-hogflow-executor',
            name: 'Test Template',
            code: exampleHog,
            inputs_schema: [
                {
                    key: 'name',
                    type: 'string',
                    required: true,
                },
                {
                    key: 'slack',
                    type: 'integration',
                    required: true,
                },
            ],
            bytecode: await compileHog(exampleHog),
        })

        await insertIntegration(hub.postgres, team.id, {
            id: 1,
            kind: 'slack',
            config: { team: 'foobar' },
            sensitive_config: {
                access_token: hub.encryptedFields.encrypt('token'),
                not_encrypted: 'not-encrypted',
            },
        })

        const hogFlow = new FixtureHogFlowBuilder()
            .withTeamId(team.id)
            .withWorkflow({
                actions: {
                    function: {
                        type: 'function',
                        config: {
                            template_id: template.template_id,
                            inputs: {
                                name: {
                                    value: 'John Doe',
                                },
                                slack: {
                                    value: 1,
                                },
                            },
                            message_category_id: 'test-category-id', // Example category ID
                        },
                    },
                    exit: {
                        type: 'exit',
                        config: {},
                    },
                },
                edges: [
                    {
                        from: 'function',
                        to: 'exit',
                        type: 'continue',
                    },
                ],
            })
            .build()

        action = findActionByType(hogFlow, 'function')!
        invocation = createExampleHogFlowInvocation(hogFlow)

        invocation.state.currentAction = {
            id: action.id,
            startedAtTimestamp: DateTime.utc().toMillis(),
        }
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('should execute a hog function with integration inputs and continue', async () => {
        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        const handlerResult = await hogFunctionHandler.execute(invocation, action, invocationResult)

        expect(mockFetch.mock.calls).toMatchInlineSnapshot(`
            [
              [
                "http://localhost/test",
                {
                  "body": "{"name":"John Doe","slack":{"team":"foobar","access_token":"token","not_encrypted":"not-encrypted"}}",
                  "headers": {
                    "Content-Type": "application/json",
                  },
                  "method": "POST",
                  "timeoutMs": 3000,
                },
              ],
            ]
        `)

        expect(handlerResult.nextAction?.id).toBe('exit')
        expect(invocationResult.logs).toHaveLength(1)
        expect(invocationResult.logs[0].message).toContain('[Action:function] Function completed')
    })

    it('should throw an error if template is not found', async () => {
        const action = findActionByType(invocation.hogFlow, 'function')!
        action.config.template_id = 'template_123'

        const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
            queue: 'hog',
            queuePriority: 0,
        })

        await expect(hogFunctionHandler.execute(invocation, action, invocationResult)).rejects.toThrow(
            "Template 'template_123' not found"
        )
    })

    describe('recipient preferences', () => {
        let mockRecipientsManagerGet: jest.SpyInstance
        let mockRecipientsManagerGetPreference: jest.SpyInstance

        beforeEach(async () => {
            mockRecipientsManagerGet = jest.spyOn(mockRecipientsManager, 'get')
            mockRecipientsManagerGetPreference = jest.spyOn(mockRecipientsManager, 'getPreference')

            // Create templates that are needed for the email and SMS tests
            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-email-native',
                name: 'Email Template',
                code: 'print("sending email")',
                inputs_schema: [],
                bytecode: await compileHog('print("sending email")'),
            })

            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-twilio',
                name: 'SMS Template',
                code: 'print("sending sms")',
                inputs_schema: [],
                bytecode: await compileHog('print("sending sms")'),
            })
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        // Helper function to create HogFlow and test execution
        const createAndTestHogFlow = async (
            actionType: 'function_email' | 'function_sms' | 'function_slack',
            config: any,
            mockRecipientData?: any,
            mockPreference?: 'OPTED_IN' | 'OPTED_OUT' | 'NO_PREFERENCE'
        ) => {
            const hogFlow = new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withWorkflow({
                    actions: {
                        [actionType.replace('function_', '')]: {
                            type: actionType,
                            config,
                        },
                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [
                        {
                            from: actionType.replace('function_', ''),
                            to: 'exit',
                            type: 'continue',
                        },
                    ],
                })
                .build()

            const actionInstance = findActionByType(hogFlow, actionType)!
            const invocationInstance = createExampleHogFlowInvocation(hogFlow)
            const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocationInstance, {
                queue: 'hog',
                queuePriority: 0,
            })

            if (mockRecipientData) {
                mockRecipientsManagerGet.mockResolvedValue(mockRecipientData)
            }
            if (mockPreference) {
                mockRecipientsManagerGetPreference.mockReturnValue(mockPreference)
            }

            return {
                result: await hogFunctionHandler.execute(invocationInstance, actionInstance, invocationResult),
                invocationResult,
                actionInstance,
            }
        }

        // Helper to create recipient data
        const createRecipient = (identifier: string, preferences: Record<string, string> = {}) => ({
            id: 'recipient-1',
            team_id: team.id,
            identifier,
            preferences,
            created_at: '2023-01-01T00:00:00Z',
            updated_at: '2023-01-01T00:00:00Z',
        })

        // Helper to create email config
        const createEmailConfig = (to: string = 'test@example.com', categoryId?: string) => ({
            template_id: 'template-email-native',
            message_category_id: categoryId || '123e4567-e89b-12d3-a456-426614174000',
            inputs: {
                email: {
                    value: { to },
                },
            },
        })

        // Helper to create SMS config
        const createSmsConfig = (toNumber: string = '+1234567890', categoryId?: string) => ({
            template_id: 'template-twilio',
            message_category_id: categoryId || '123e4567-e89b-12d3-a456-426614174000',
            inputs: {
                to_number: {
                    value: toNumber,
                },
            },
        })

        // Helper to create Slack config
        const createSlackConfig = () => ({
            template_id: 'template-slack',
            inputs: {
                channel: {
                    value: '#general',
                },
            },
        })

        describe('isSubjectToRecipientPreferences', () => {
            it('should return true for function_email actions', async () => {
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN',
                })
                const { result } = await createAndTestHogFlow(
                    'function_email',
                    createEmailConfig(),
                    recipient,
                    'OPTED_IN'
                )

                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: 'test@example.com',
                })
                expect(result.nextAction?.id).toBe('exit')
            })

            it('should return true for function_sms actions', async () => {
                const recipient = createRecipient('+1234567890', { '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN' })
                const { result } = await createAndTestHogFlow('function_sms', createSmsConfig(), recipient, 'OPTED_IN')

                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: '+1234567890',
                })
                expect(result.nextAction?.id).toBe('exit')
            })

            it('should return false for function actions', async () => {
                const invocationResult = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation, {
                    queue: 'hog',
                    queuePriority: 0,
                })

                await hogFunctionHandler.execute(invocation, action, invocationResult)

                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })

            it('should return false for function_slack actions', async () => {
                await createAndTestHogFlow('function_slack', createSlackConfig())
                expect(mockRecipientsManagerGet).not.toHaveBeenCalled()
            })
        })

        describe('checkRecipientPreferences for email', () => {
            it('should skip execution if recipient is opted out', async () => {
                const recipient = createRecipient('test@example.com', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT',
                })
                const { result, invocationResult } = await createAndTestHogFlow(
                    'function_email',
                    createEmailConfig(),
                    recipient,
                    'OPTED_OUT'
                )

                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: 'test@example.com',
                })
                expect(mockRecipientsManagerGetPreference).toHaveBeenCalledWith(
                    expect.any(Object),
                    '123e4567-e89b-12d3-a456-426614174000'
                )
                expect(result.nextAction?.id).toBe('exit')
                expect(invocationResult.logs).toHaveLength(1)
                expect(invocationResult.logs[0].message).toContain('Recipient opted out for action email')
            })

            it('should use $all category when message_category_id is not provided', async () => {
                const config = createEmailConfig()
                // Use type assertion to allow deletion for test purposes
                delete (config as any).message_category_id
                const recipient = createRecipient('test@example.com', { $all: 'OPTED_OUT' })
                const { result, invocationResult } = await createAndTestHogFlow(
                    'function_email',
                    config,
                    recipient,
                    'OPTED_OUT'
                )

                expect(mockRecipientsManagerGetPreference).toHaveBeenCalledWith(expect.any(Object), '$all')
                expect(result.nextAction?.id).toBe('exit')
                expect(invocationResult.logs[0].message).toContain('Recipient opted out for action email')
            })

            it('should proceed if recipient is not found', async () => {
                mockRecipientsManagerGet.mockResolvedValue(null)
                const { result, invocationResult } = await createAndTestHogFlow('function_email', createEmailConfig())

                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: 'test@example.com',
                })
                expect(mockRecipientsManagerGetPreference).not.toHaveBeenCalled()
                expect(result.nextAction?.id).toBe('exit')
                expect(invocationResult.logs).toHaveLength(1)
                expect(invocationResult.logs[0].message).toContain('Function completed')
            })

            it('should proceed if recipient has no preference or is opted in', async () => {
                const recipient = createRecipient('test@example.com', {})
                const { result, invocationResult } = await createAndTestHogFlow(
                    'function_email',
                    createEmailConfig(),
                    recipient,
                    'NO_PREFERENCE'
                )

                expect(result.nextAction?.id).toBe('exit')
                expect(invocationResult.logs).toHaveLength(1)
                expect(invocationResult.logs[0].message).toContain('Function completed')
            })

            it('should handle errors when fetching recipient preferences', async () => {
                mockRecipientsManagerGet.mockRejectedValue(new Error('Database error'))
                const consoleSpy = jest.spyOn(console, 'error').mockImplementation()

                const { result, invocationResult } = await createAndTestHogFlow('function_email', createEmailConfig())

                expect(consoleSpy).toHaveBeenCalledWith(
                    'Failed to fetch recipient preferences for test@example.com:',
                    expect.any(Error)
                )
                expect(result.nextAction?.id).toBe('exit')
                expect(invocationResult.logs).toHaveLength(1)
                expect(invocationResult.logs[0].message).toContain('Function completed')

                consoleSpy.mockRestore()
            })

            it('should throw error if no email identifier is found', async () => {
                const config = createEmailConfig()
                // Use type assertion to allow deletion for test purposes
                delete (config.inputs.email.value as any).to

                await expect(createAndTestHogFlow('function_email', config)).rejects.toThrow(
                    'No identifier found for message action email'
                )
            })
        })

        describe('checkRecipientPreferences for SMS', () => {
            it('should skip execution if SMS recipient is opted out', async () => {
                const recipient = createRecipient('+1234567890', {
                    '123e4567-e89b-12d3-a456-426614174000': 'OPTED_OUT',
                })
                const { result, invocationResult } = await createAndTestHogFlow(
                    'function_sms',
                    createSmsConfig(),
                    recipient,
                    'OPTED_OUT'
                )

                expect(mockRecipientsManagerGet).toHaveBeenCalledWith({
                    teamId: team.id,
                    identifier: '+1234567890',
                })
                expect(result.nextAction?.id).toBe('exit')
                expect(invocationResult.logs[0].message).toContain('Recipient opted out for action sms')
            })

            it('should proceed if SMS recipient is opted in', async () => {
                const recipient = createRecipient('+1234567890', { '123e4567-e89b-12d3-a456-426614174000': 'OPTED_IN' })
                const { result, invocationResult } = await createAndTestHogFlow(
                    'function_sms',
                    createSmsConfig(),
                    recipient,
                    'OPTED_IN'
                )

                expect(result.nextAction?.id).toBe('exit')
                expect(invocationResult.logs).toHaveLength(1)
                expect(invocationResult.logs[0].message).toContain('Function completed')
            })

            it('should throw error if no SMS identifier is found', async () => {
                const config = createSmsConfig()
                // Use type assertion to allow deletion for test purposes
                delete (config.inputs as any).to_number

                await expect(createAndTestHogFlow('function_sms', config)).rejects.toThrow(
                    'No identifier found for message action sms'
                )
            })
        })
    })
})
