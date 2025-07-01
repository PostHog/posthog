jest.mock('~/utils/request', () => {
    const original = jest.requireActual('~/utils/request')
    return {
        ...original,
        fetch: jest.fn().mockImplementation((url, options) => {
            return original.fetch(url, options)
        }),
    }
})

import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createHogExecutionGlobals, insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { compileHog } from '~/cdp/templates/compiler'
import { HogFlow } from '~/schema/hogflow'
import { resetTestDatabase } from '~/tests/helpers/sql'
import { fetch } from '~/utils/request'

import { Hub } from '../../../types'
import { createHub } from '../../../utils/db/hub'
import { HOG_FILTERS_EXAMPLES } from '../../_tests/examples'
import { createExampleHogFlowInvocation } from '../../_tests/fixtures-hogflows'
import { HogExecutorService } from '../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { HogFlowExecutorService } from './hogflow-executor.service'

const cleanLogs = (logs: string[]): string[] => {
    // Replaces the function time with a fixed value to simplify testing
    return logs.map((log) => {
        return log.replace(/Function completed in \d+(\.\d+)?ms/, 'Function completed in REPLACEDms')
    })
}

describe('Hogflow Executor', () => {
    let executor: HogFlowExecutorService
    let hub: Hub
    const mockFetch = jest.mocked(fetch)

    beforeEach(async () => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        mockFetch.mockImplementation((): any => {
            return {
                status: 200,
                text: () => Promise.resolve(JSON.stringify({ status: 200 })),
            }
        })

        await resetTestDatabase()
        hub = await createHub()
        const hogExecutor = new HogExecutorService(hub)
        const hogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub)

        const exampleHog = `
            print(f'Hello, {inputs.name}!')
            print('Fetch 1', fetch('https://posthog.com').status)`

        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-test-hogflow-executor',
            name: 'Test Template',
            hog: exampleHog,
            inputs_schema: [
                {
                    key: 'name',
                    type: 'string',
                    required: true,
                },
            ],
            bytecode: await compileHog(exampleHog),
        })

        const exampleHogMultiFetch = `
            print(f'Hello, {inputs.name}!')
            print('Fetch 1', fetch('https://posthog.com').status)
            print('Fetch 2', fetch('https://posthog.com').status)
            print('Fetch 3', fetch('https://posthog.com').status)
            print('All fetches done!')`

        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-test-hogflow-executor-async',
            name: 'Test template multi fetch',
            hog: exampleHogMultiFetch,
            inputs_schema: [
                {
                    key: 'name',
                    type: 'string',
                    required: true,
                },
            ],
            bytecode: await compileHog(exampleHogMultiFetch),
        })

        executor = new HogFlowExecutorService(hub, hogExecutor, hogFunctionTemplateManager)
    })

    describe('general event processing', () => {
        let hogFlow: HogFlow

        beforeEach(async () => {
            hogFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: {
                                type: 'event',
                                filters: HOG_FILTERS_EXAMPLES.no_filters.filters,
                            },
                        },

                        function_id_1: {
                            type: 'function',
                            config: {
                                template_id: 'template-test-hogflow-executor',
                                inputs: {
                                    name: {
                                        value: `Mr {event?.properties?.name}`,
                                        bytecode: await compileHog(`return f'Mr {event?.properties?.name}'`),
                                    },
                                },
                            },
                        },

                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [
                        {
                            from: 'trigger',
                            to: 'function_id_1',
                            type: 'continue',
                        },
                        {
                            from: 'function_id_1',
                            to: 'exit',
                            type: 'continue',
                        },
                    ],
                })
                .build()
        })

        it('can execute a simple hogflow', async () => {
            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    properties: {
                        name: 'John Doe',
                    },
                },
            })

            const result = await executor.execute(invocation)

            expect(result).toEqual({
                capturedPostHogEvents: [],
                invocation: {
                    state: {
                        actionStepCount: 1,
                        currentAction: {
                            id: 'exit',
                            startedAtTimestamp: expect.any(Number),
                        },
                        event: {
                            distinct_id: 'distinct_id',
                            elements_chain: '',
                            event: 'test',
                            properties: {
                                name: 'John Doe',
                            },
                            timestamp: expect.any(String),
                            url: 'http://localhost:8000/events/1',
                            uuid: 'uuid',
                        },
                    },
                    id: expect.any(String),
                    teamId: 1,
                    hogFlow: invocation.hogFlow,
                    functionId: invocation.hogFlow.id,
                    queue: 'hogflow',
                    queueMetadata: undefined,
                    queueScheduledAt: undefined,
                    queueSource: undefined,
                    queueParameters: undefined,
                    queuePriority: 0,
                },
                finished: true,
                logs: [
                    {
                        level: 'info',
                        timestamp: expect.any(DateTime),
                        message: '[Action:function_id_1] Hello, Mr John Doe!',
                    },
                    {
                        level: 'info',
                        timestamp: expect.any(DateTime),
                        message: '[Action:function_id_1] Fetch 1, 200',
                    },
                    {
                        level: 'debug',
                        timestamp: expect.any(DateTime),
                        message: expect.stringContaining('[Action:function_id_1] Function completed in'),
                    },
                    {
                        level: 'info',
                        timestamp: expect.any(DateTime),
                        message: "Workflow moved to action 'exit (exit)'",
                    },
                    {
                        level: 'info',
                        timestamp: expect.any(DateTime),
                        message: 'Workflow completed',
                    },
                ],
                metrics: [
                    {
                        team_id: hogFlow.team_id,
                        app_source_id: hogFlow.id,
                        instance_id: 'function_id_1',
                        metric_kind: 'success',
                        metric_name: 'succeeded',
                        count: 1,
                    },
                    {
                        team_id: hogFlow.team_id,
                        app_source_id: hogFlow.id,
                        instance_id: 'exit',
                        metric_kind: 'success',
                        metric_name: 'succeeded',
                        count: 1,
                    },
                ],
            })
        })

        it('can execute a hogflow with async function delays', async () => {
            const action = hogFlow.actions.find((action) => action.id === 'function_id_1')!
            ;(action.config as any).template_id = 'template-test-hogflow-executor-async'

            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    properties: {
                        name: 'John Doe',
                    },
                },
            })

            const result = await executor.execute(invocation)

            expect(result.finished).toEqual(false)
            expect(result.invocation.state.hogFunctionState).toEqual(expect.any(Object))
            expect(result.invocation.queueScheduledAt).toEqual(expect.any(DateTime))
            expect(result.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "[Action:function_id_1] Hello, Mr John Doe!",
                  "[Action:function_id_1] Fetch 1, 200",
                  "Workflow will pause until 2025-01-01T01:00:00.000+01:00",
                ]
            `)

            const result2 = await executor.execute(result.invocation)

            expect(result2.finished).toEqual(false)
            expect(result2.invocation.state.hogFunctionState).toEqual(expect.any(Object))
            expect(result2.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "[Action:function_id_1] Fetch 2, 200",
                  "Workflow will pause until 2025-01-01T01:00:00.000+01:00",
                ]
            `)

            const result3 = await executor.execute(result2.invocation)

            expect(result3.finished).toEqual(true)
            expect(cleanLogs(result3.logs.map((log) => log.message))).toMatchInlineSnapshot(`
                [
                  "[Action:function_id_1] Fetch 3, 200",
                  "[Action:function_id_1] All fetches done!",
                  "[Action:function_id_1] Function completed in REPLACEDms. Sync: 0ms. Mem: 101 bytes. Ops: 32. Event: 'http://localhost:8000/events/1'",
                  "Workflow moved to action 'exit (exit)'",
                  "Workflow completed",
                ]
            `)
        })
    })
})
