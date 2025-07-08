import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
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

    beforeEach(() => {
        hub = {
            SITE_URL: 'http://localhost:8000',
        } as Hub

        hogFunctionExecutor = new (HogExecutorService as any)() as jest.Mocked<HogExecutorService>
        hogFunctionTemplateManager =
            new (HogFunctionTemplateManagerService as any)() as jest.Mocked<HogFunctionTemplateManagerService>
        handler = new HogFunctionHandler(hub, hogFunctionExecutor, hogFunctionTemplateManager)

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
        const template = {
            id: 'template-123',
            name: 'Test Template',
            bytecode: [1, 2, 3],
        }
        hogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(template as any)

        const functionResult: CyclotronJobInvocationResult<any> = {
            finished: true,
            logs: [{ level: 'info', message: 'Function executed', timestamp: DateTime.now() }],
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
        }
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
        const template = {
            id: 'template-123',
            name: 'Test Template',
            bytecode: [1, 2, 3],
        }
        hogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(template as any)

        const scheduledAt = DateTime.now().plus({ minutes: 5 })
        const functionResult: CyclotronJobInvocationResult<any> = {
            finished: false,
            logs: [],
            metrics: [],
            capturedPostHogEvents: [],
            invocation: {
                ...invocation,
                queueScheduledAt: scheduledAt,
                state: {
                    globals: {},
                    timings: [],
                    attempts: 1,
                },
            },
        }
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
        const template = {
            id: 'template-123',
            name: 'Test Template',
            bytecode: [1, 2, 3],
        }
        hogFunctionTemplateManager.getHogFunctionTemplate.mockResolvedValue(template as any)

        const logTimestamp = DateTime.now()
        const functionResult: CyclotronJobInvocationResult<any> = {
            finished: true,
            logs: [{ level: 'info', message: 'Function log', timestamp: logTimestamp }],
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
        }
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
})
