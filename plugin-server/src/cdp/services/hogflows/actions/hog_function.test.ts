import { DateTime } from 'luxon'

import { HogFlowAction } from '../../../../schema/hogflow'
import { Hub } from '../../../../types'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationResult,
    DBHogFunctionTemplate,
    HogFunctionType,
    MinimalLogEntry,
} from '../../../types'
import { HogExecutorService } from '../../hog-executor.service'
import { HogFunctionManagerService } from '../../managers/hog-function-manager.service'
import { HogFunctionTemplateManagerService } from '../../managers/hog-function-template-manager.service'
import { HogFunctionHandler } from './hog_function'

jest.mock('../../hog-executor.service')
jest.mock('../../managers/hog-function-manager.service')
jest.mock('../../managers/hog-function-template-manager.service')

describe('HogFunctionHandler', () => {
    let hogFunctionHandler: HogFunctionHandler
    let mockHub: jest.Mocked<Hub>
    let mockHogFunctionExecutor: jest.Mocked<HogExecutorService>
    let mockHogFunctionManager: jest.Mocked<HogFunctionManagerService>
    let mockHogFunctionTemplateManager: jest.Mocked<HogFunctionTemplateManagerService>

    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'function' }>
    let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>

    beforeEach(() => {
        mockHub = {
            SITE_URL: 'http://test.posthog.com',
        } as any

        mockHogFunctionExecutor = new (HogExecutorService as any)()
        mockHogFunctionManager = new (HogFunctionManagerService as any)()
        mockHogFunctionTemplateManager = new (HogFunctionTemplateManagerService as any)()

        hogFunctionHandler = new HogFunctionHandler(
            mockHub,
            mockHogFunctionExecutor,
            mockHogFunctionManager,
            mockHogFunctionTemplateManager
        )

        invocation = {
            id: 'inv_123',
            teamId: 1,
            hogFlow: {
                id: 'flow_123',
                team_id: 1,
                name: 'My Hog Flow',
            },
            state: {
                event: {
                    uuid: 'evt_123',
                    name: 'test event',
                    distinct_id: 'user123',
                    properties: {},
                    timestamp: new Date().toISOString(),
                },
            },
            queueParameters: {},
        } as CyclotronJobInvocationHogFlow

        action = {
            id: 'action_123',
            type: 'function',
            config: {
                template_id: 'template_123',
                inputs: {},
            },
            name: 'Test Action',
            description: 'Test Description',
            created_at: new Date().getTime(),
            updated_at: new Date().getTime(),
        }

        result = {
            invocation: invocation,
            logs: [],
            metrics: [],
            finished: false,
            capturedPostHogEvents: [],
        }
    })

    it('should execute a hog function and continue', async () => {
        const template: DBHogFunctionTemplate = {
            id: 'uuid',
            template_id: 'template_123',
            name: 'Test Template',
            bytecode: [1, 2, 3],
            inputs_schema: [],
            sha: 'sha',
            type: 'destination',
        }
        mockHogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(template)

        const functionResult = {
            finished: true,
            logs: [{ level: 'info', message: 'Function executed', timestamp: DateTime.now() } as MinimalLogEntry],
            invocation: {
                ...invocation,
                hogFunction: {} as HogFunctionType,
                state: {},
            },
        }
        mockHogFunctionExecutor.executeWithAsyncFunctions.mockResolvedValue(functionResult as any)

        const handlerResult = await hogFunctionHandler.execute(invocation, action, result)

        expect(mockHogFunctionTemplateManager.getHogFunctionTemplate).toHaveBeenCalledWith('template_123')
        expect(mockHogFunctionManager.enrichWithIntegrations).toHaveBeenCalled()
        expect(mockHogFunctionExecutor.executeWithAsyncFunctions).toHaveBeenCalled()
        expect(result.logs).toHaveLength(1)
        expect(result.logs[0].message).toBe('[Action:action_123] Function executed')
        expect(handlerResult.nextAction).not.toBeUndefined()
        expect(handlerResult.scheduledAt).toBeUndefined()
    })

    it('should handle unfinished function execution and schedule continuation', async () => {
        const template: DBHogFunctionTemplate = {
            id: 'uuid',
            template_id: 'template_123',
            name: 'Test Template',
            bytecode: [1, 2, 3],
            inputs_schema: [],
            sha: 'sha',
            type: 'destination',
        }
        mockHogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(template)

        const scheduledAt = DateTime.now().plus({ minutes: 5 })
        const functionResult = {
            finished: false,
            logs: [],
            invocation: {
                ...invocation,
                hogFunction: {} as HogFunctionType,
                state: { globals: {}, timings: [], attempts: 1 },
                queueScheduledAt: scheduledAt,
                queueParameters: { some: 'param' },
            },
        }
        mockHogFunctionExecutor.executeWithAsyncFunctions.mockResolvedValue(functionResult as any)

        const handlerResult = await hogFunctionHandler.execute(invocation, action, result)

        expect(result.invocation.state.hogFunctionState).toEqual(functionResult.invocation.state)
        expect(result.invocation.queueParameters).toEqual({ some: 'param' })
        expect(handlerResult.scheduledAt).toEqual(scheduledAt)
        expect(handlerResult.nextAction).toBeUndefined()
    })

    it('should throw an error if template is not found', async () => {
        mockHogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(null)

        await expect(hogFunctionHandler.execute(invocation, action, result)).rejects.toThrow(
            "Template 'template_123' not found"
        )
    })

    it('enriches the hog function with integrations', async () => {
        const template: DBHogFunctionTemplate = {
            id: 'uuid',
            template_id: 'template_123',
            name: 'Test Template',
            bytecode: [1, 2, 3],
            inputs_schema: [],
            sha: 'sha',
            type: 'destination',
        }
        mockHogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(template)

        const functionResult = {
            finished: true,
            logs: [],
            invocation: {
                ...invocation,
                hogFunction: {} as HogFunctionType,
                state: {},
            },
        }
        mockHogFunctionExecutor.executeWithAsyncFunctions.mockResolvedValue(functionResult as any)

        await hogFunctionHandler.execute(invocation, action, result)

        expect(mockHogFunctionManager.enrichWithIntegrations).toHaveBeenCalledTimes(1)
        const enrichWithIntegrationsCall = mockHogFunctionManager.enrichWithIntegrations.mock.calls[0][0]
        expect(enrichWithIntegrationsCall).toHaveLength(1)
        const hogFunctionArg = enrichWithIntegrationsCall[0]
        expect(hogFunctionArg.id).toBe(invocation.hogFlow.id)
        expect(hogFunctionArg.team_id).toBe(invocation.teamId)
        expect(hogFunctionArg.name).toBe('My Hog Flow - Test Template')
    })
})
