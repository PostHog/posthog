import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult, DBHogFunctionTemplate } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'
import { Hub } from '~/types'

import { HogExecutorService } from '../../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../../managers/hog-function-template-manager.service'
import { findActionById, findActionByType } from '../hogflow-utils'
import { HogFunctionHandler } from './hog_function'

jest.mock('../../hog-executor.service')
jest.mock('../../managers/hog-function-template-manager.service')

describe('HogFunctionHandler', () => {
    let hub: Hub
    let hogFunctionExecutor: jest.Mocked<HogExecutorService>
    let hogFunctionTemplateManager: jest.Mocked<HogFunctionTemplateManagerService>
    let handler: HogFunctionHandler
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'function' }>
    let template: DBHogFunctionTemplate

    const createFunctionResult = (
        finished: boolean,
        props: Partial<CyclotronJobInvocationResult<any>> = {}
    ): CyclotronJobInvocationResult<any> => ({
        finished,
        logs: [],
        metrics: [],
        capturedPostHogEvents: [],
        invocation: {
            ...invocation,
            state: {
                globals: {},
                timings: [],
                attempts: 1,
            },
        },
        ...props,
    })

    beforeEach(() => {
        hub = {
            SITE_URL: 'http://localhost:8000',
        } as Hub

        hogFunctionExecutor = new (HogExecutorService as any)() as jest.Mocked<HogExecutorService>
        hogFunctionTemplateManager =
            new (HogFunctionTemplateManagerService as any)() as jest.Mocked<HogFunctionTemplateManagerService>
        handler = new HogFunctionHandler(hub, hogFunctionExecutor, hogFunctionTemplateManager)

        template = {
            id: 'template-123',
            name: 'Test Template',
            inputs_schema: [],
            template_id: 'template-123',
            sha: '123',
            bytecode: [1, 2, 3],
            type: 'destination',
        }
        hogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(template)

        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    hog_function: {
                        type: 'function',
                        config: {
                            template_id: 'template-123',
                            inputs: {
                                text: { value: 'Hello world' },
                            },
                        },
                    },
                    success: {
                        type: 'delay',
                        config: {
                            delay_duration: '1h',
                        },
                    },
                },
                edges: [
                    {
                        from: 'hog_function',
                        to: 'success',
                        type: 'continue',
                    },
                ],
            })
            .build()

        action = findActionByType(hogFlow, 'function')!
        invocation = createExampleHogFlowInvocation(hogFlow)
        invocation.getPerson = jest.fn().mockResolvedValue({
            uuid: 'person-uuid',
            properties: { email: 'test@posthog.com' },
        })
    })

    it('executes a hog function and continues to the next action', async () => {
        const functionResult = createFunctionResult(true, {
            logs: [{ level: 'info', message: 'Function executed', timestamp: DateTime.now() }],
        })
        hogFunctionExecutor.executeWithAsyncFunctions.mockResolvedValue(functionResult)

        const result = await handler.execute(invocation, action, {
            invocation,
            logs: [],
            finished: false,
            metrics: [],
            capturedPostHogEvents: [],
        })

        expect(result).toEqual({
            nextAction: findActionById(invocation.hogFlow, 'success'),
        })
        expect(hogFunctionTemplateManager.getHogFunctionTemplate).toHaveBeenCalledWith('template-123')
        expect(hogFunctionExecutor.executeWithAsyncFunctions).toHaveBeenCalled()
    })

    it('reschedules if the hog function is not finished', async () => {
        const scheduledAt = DateTime.now().plus({ minutes: 5 })
        const functionResult = createFunctionResult(false, {
            invocation: {
                ...invocation,
                queueScheduledAt: scheduledAt,
                state: {
                    globals: {},
                    timings: [],
                    attempts: 1,
                },
            },
        })
        hogFunctionExecutor.executeWithAsyncFunctions.mockResolvedValue(functionResult)

        const result = await handler.execute(invocation, action, {
            invocation,
            logs: [],
            finished: false,
            metrics: [],
            capturedPostHogEvents: [],
        })

        expect(result).toEqual({
            scheduledAt,
        })
    })

    it('throws an error if the template is not found', async () => {
        hogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(null)

        await expect(
            handler.execute(invocation, action, {
                invocation,
                logs: [],
                finished: false,
                metrics: [],
                capturedPostHogEvents: [],
            })
        ).rejects.toThrow("Template 'template-123' not found")
    })

    it('adds logs from the function execution to the result', async () => {
        const logTimestamp = DateTime.now()
        const functionResult = createFunctionResult(true, {
            logs: [{ level: 'info', message: 'Function log', timestamp: logTimestamp }],
        })
        hogFunctionExecutor.executeWithAsyncFunctions.mockResolvedValue(functionResult)

        const resultContainer: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow> = {
            invocation,
            logs: [],
            finished: false,
            metrics: [],
            capturedPostHogEvents: [],
        }
        await handler.execute(invocation, action, resultContainer)

        expect(resultContainer.logs).toEqual([
            {
                level: 'info',
                message: `[Action:${action.id}] Function log`,
                timestamp: logTimestamp,
            },
        ])
    })

    it('adds person data to the hog function globals', async () => {
        const functionResult = createFunctionResult(true)
        hogFunctionExecutor.executeWithAsyncFunctions.mockResolvedValue(functionResult)

        const person = {
            uuid: 'person-uuid-123',
            properties: { email: 'test@posthog.com', name: 'Test User' },
        }
        invocation.getPerson = jest.fn().mockResolvedValue(person)

        await handler.execute(invocation, action, {
            invocation,
            logs: [],
            finished: false,
            metrics: [],
            capturedPostHogEvents: [],
        })

        expect(invocation.getPerson).toHaveBeenCalled()
        expect(hogFunctionExecutor.executeWithAsyncFunctions).toHaveBeenCalled()

        const executedInvocation = hogFunctionExecutor.executeWithAsyncFunctions.mock.calls[0][0]
        expect(executedInvocation.state.globals.person).toMatchObject({
            uuid: person.uuid,
            properties: person.properties,
        })
    })
})
