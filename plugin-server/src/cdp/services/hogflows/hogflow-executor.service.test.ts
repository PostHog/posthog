// sort-imports-ignore
import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from '~/cdp/_tests/builders/hogflow.builder'
import { createHogExecutionGlobals, insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { compileHog } from '~/cdp/templates/compiler'
import { template as posthogCaptureTemplate } from '~/cdp/templates/_destinations/posthog_capture/posthog-capture.template'
import { HogFlow } from '~/schema/hogflow'
import { resetTestDatabase } from '~/tests/helpers/sql'

import { fetch } from '~/utils/request'
import { Hub } from '../../../types'
import { createHub } from '../../../utils/db/hub'
import { HOG_FILTERS_EXAMPLES } from '../../_tests/examples'
import { createExampleHogFlowInvocation } from '../../_tests/fixtures-hogflows'
import { HogExecutorService } from '../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { RecipientPreferencesService } from '../messaging/recipient-preferences.service'
import { HogFlowExecutorService } from './hogflow-executor.service'
import { HogFlowFunctionsService } from './hogflow-functions.service'

// Mock before importing fetch
jest.mock('~/utils/request', () => {
    const original = jest.requireActual('~/utils/request')
    return {
        ...original,
        fetch: jest.fn().mockImplementation((url, options) => {
            return original.fetch(url, options)
        }),
    }
})

const cleanLogs = (logs: string[]): string[] => {
    // Replaces the function time with a fixed value to simplify testing
    return logs.map((log) => log.replace(/Function completed in \d+(\.\d+)?ms/, 'Function completed in REPLACEDms'))
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
        hub = await createHub({
            SITE_URL: 'http://localhost:8000',
        })
        const hogExecutor = new HogExecutorService(hub)
        const hogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub)
        const hogFlowFunctionsService = new HogFlowFunctionsService(hub, hogFunctionTemplateManager, hogExecutor)
        const recipientsManager = new RecipientsManagerService(hub)
        const recipientPreferencesService = new RecipientPreferencesService(recipientsManager)

        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-test-hogflow-executor',
            name: 'Test Template',
            code: `
            print(f'Hello, {inputs.name}!')
            print('Fetch 1', fetch('https://posthog.com').status)`,
            inputs_schema: [
                {
                    key: 'name',
                    type: 'string',
                    required: true,
                },
            ],
        })

        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-test-hogflow-executor-async',
            name: 'Test template multi fetch',
            code: `
            print(f'Hello, {inputs.name}!')
            print('Fetch 1', fetch('https://posthog.com').status)
            print('Fetch 2', fetch('https://posthog.com').status)
            print('Fetch 3', fetch('https://posthog.com').status)
            print('All fetches done!')`,
            inputs_schema: [
                {
                    key: 'name',
                    type: 'string',
                    required: true,
                },
            ],
        })

        await insertHogFunctionTemplate(hub.postgres, posthogCaptureTemplate)

        executor = new HogFlowExecutorService(hogFlowFunctionsService, recipientPreferencesService)
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
                                filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
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
                    person: {
                        id: 'person_id',
                        name: '',
                        properties: {
                            name: 'John Doe',
                        },
                        url: '',
                    },
                    filterGlobals: expect.any(Object),
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
                        level: 'debug',
                        message: 'Starting workflow execution at trigger',
                        timestamp: expect.any(DateTime),
                    },
                    {
                        level: 'debug',
                        message: 'Executing action [Action:function_id_1]',
                        timestamp: expect.any(DateTime),
                    },
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
                        message: 'Workflow moved to action [Action:exit]',
                    },
                    {
                        level: 'debug',
                        timestamp: expect.any(DateTime),
                        message: 'Executing action [Action:exit]',
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
            expect(result.invocation.state.currentAction!.hogFunctionState).toEqual(expect.any(Object))
            expect(result.invocation.queueScheduledAt).toEqual(expect.any(DateTime))
            expect(result.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "Starting workflow execution at trigger",
                  "Executing action [Action:function_id_1]",
                  "[Action:function_id_1] Hello, Mr John Doe!",
                  "[Action:function_id_1] Fetch 1, 200",
                  "Workflow will pause until 2025-01-01T00:00:00.000Z",
                ]
            `)

            const result2 = await executor.execute(result.invocation)

            expect(result2.finished).toEqual(false)
            expect(result2.invocation.state.currentAction!.hogFunctionState).toEqual(expect.any(Object))
            expect(result2.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "Resuming workflow execution at [Action:function_id_1]",
                  "Executing action [Action:function_id_1]",
                  "[Action:function_id_1] Fetch 2, 200",
                  "Workflow will pause until 2025-01-01T00:00:00.000Z",
                ]
            `)

            const result3 = await executor.execute(result2.invocation)

            expect(result3.finished).toEqual(true)
            expect(cleanLogs(result3.logs.map((log) => log.message))).toMatchInlineSnapshot(`
                [
                  "Resuming workflow execution at [Action:function_id_1]",
                  "Executing action [Action:function_id_1]",
                  "[Action:function_id_1] Fetch 3, 200",
                  "[Action:function_id_1] All fetches done!",
                  "[Action:function_id_1] Function completed in REPLACEDms. Sync: 0ms. Mem: 0.099kb. Ops: 32. Event: 'http://localhost:8000/events/1'",
                  "Workflow moved to action [Action:exit]",
                  "Executing action [Action:exit]",
                  "Workflow completed",
                ]
            `)
        })

        describe('action filtering', () => {
            beforeEach(() => {
                const action = hogFlow.actions.find((action) => action.id === 'function_id_1')!
                action.filters = HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters
            })

            it('should only run the action if the provided filters match', async () => {
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                        },
                    },
                })

                const result = await executor.execute(invocation)

                expect(result.finished).toEqual(true)
                expect(mockFetch).toHaveBeenCalledTimes(1)
                expect(result.metrics.find((x) => x.instance_id === 'function_id_1')).toMatchObject({
                    count: 1,
                    instance_id: 'function_id_1',
                    metric_kind: 'success',
                    metric_name: 'succeeded',
                })
            })

            it('should skip the action if the filters do not match', async () => {
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: 'not-a-pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                        },
                    },
                })

                const result = await executor.execute(invocation)

                expect(result.finished).toEqual(true)
                expect(mockFetch).toHaveBeenCalledTimes(0)
                expect(result.metrics.find((x) => x.instance_id === 'function_id_1')).toMatchObject({
                    count: 1,
                    instance_id: 'function_id_1',
                    metric_kind: 'other',
                    metric_name: 'filtered',
                })
            })
        })

        describe('executeTest', () => {
            it('executes only a single step at a time', async () => {
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        properties: {
                            name: 'Debug User',
                        },
                    },
                })

                // NOTE: Slightly contrived as we dont set the current action to trigger when creating the invocation
                // but we do support it technically from the frontend
                invocation.state.currentAction = {
                    id: 'trigger',
                    startedAtTimestamp: DateTime.now().toMillis(),
                }

                // First step: should process trigger and move to function_id_1, but not complete
                const result1 = await executor.executeCurrentAction(invocation)
                expect(result1.finished).toBe(false)
                expect(result1.invocation.state.currentAction?.id).toBe('function_id_1')
                expect(result1.logs.map((log) => log.message)).toEqual([
                    'Executing action [Action:trigger]',
                    'Workflow moved to action [Action:function_id_1]',
                ])

                // Second step: should process function_id_1 and move to exit, but not complete
                const result2 = await executor.execute(result1.invocation)
                expect(result2.finished).toBe(true)
                expect(result2.invocation.state.currentAction?.id).toBe('exit')
                expect(result2.logs.map((log) => log.message)).toEqual([
                    'Resuming workflow execution at [Action:function_id_1]',
                    'Executing action [Action:function_id_1]',
                    '[Action:function_id_1] Hello, Mr Debug User!',
                    '[Action:function_id_1] Fetch 1, 200',
                    expect.stringContaining('[Action:function_id_1] Function completed in'),
                    'Workflow moved to action [Action:exit]',
                    'Executing action [Action:exit]',
                    'Workflow completed',
                ])
            })
        })
    })

    describe('actions', () => {
        const createHogFlow = (flow: SimpleHogFlowRepresentation): HogFlow => {
            return new FixtureHogFlowBuilder()
                .withExitCondition('exit_on_conversion')
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: {
                                type: 'event',
                                filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                            },
                        },
                        delay: {
                            type: 'delay',
                            config: {
                                delay_duration: '2h',
                            },
                        },
                        exit: {
                            type: 'exit',
                            config: {},
                        },
                        ...flow.actions,
                    },
                    edges: flow.edges,
                })
                .build()
        }

        describe('early exit conditions', () => {
            let hogFlow: HogFlow

            beforeEach(async () => {
                // Setup: exit if person no longer matches trigger filters
                hogFlow = new FixtureHogFlowBuilder()
                    .withExitCondition('exit_only_at_end')
                    .withWorkflow({
                        actions: {
                            trigger: {
                                type: 'trigger',
                                config: {
                                    type: 'event',
                                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters ?? {},
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
                            { from: 'trigger', to: 'function_id_1', type: 'continue' },
                            { from: 'function_id_1', to: 'exit', type: 'continue' },
                        ],
                    })
                    .build()
            })

            it('should not exit early if exit condition is exit_only_at_end', async () => {
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })

                // Step 1: run first action (function_id_1)
                const result1 = await executor.execute(invocation)
                expect(result1.finished).toBe(true)
                expect(result1.metrics.map((m) => m.metric_name)).toEqual(['succeeded', 'succeeded'])

                const invocation2 = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: 'not-a-pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })

                // Step 2: run again, should NOT exit early due to exit_only_at_end
                const result2 = await executor.execute(invocation2)
                expect(result2.finished).toBe(true)
                expect(result2.metrics.map((m) => m.metric_name)).toEqual(['succeeded', 'succeeded'])
            })

            it('should exit early if exit condition is exit_on_conversion', async () => {
                hogFlow.exit_condition = 'exit_on_conversion'
                hogFlow.conversion = {
                    window_minutes: 10,
                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
                }

                // Simulate a non-conversion event
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$not-a-pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com', conversion: true },
                    },
                })

                const result1 = await executor.execute(invocation)
                expect(result1.finished).toBe(true)
                expect(result1.metrics.map((m) => m.metric_name)).toEqual(['succeeded', 'succeeded'])

                const invocation2 = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com', conversion: true },
                    },
                })
                const result2 = await executor.execute(invocation2)
                expect(result2.finished).toBe(true)
                expect(result2.metrics.map((m) => m.metric_name)).toEqual(['early_exit'])
                expect(result2.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                    [
                      "Workflow exited early due to exit condition: exit_on_conversion (Person matches conversion filters)",
                    ]
                `)
            })

            it('should exit early if exit condition is exit_on_trigger_not_matched', async () => {
                hogFlow.exit_condition = 'exit_on_trigger_not_matched'
                hogFlow.trigger = {
                    type: 'event',
                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters ?? {},
                }

                const invocation1 = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })

                const result1 = await executor.execute(invocation1)
                expect(result1.finished).toBe(true)
                expect(result1.metrics.map((m) => m.metric_name)).toEqual(['succeeded', 'succeeded'])

                const invocation2 = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$not-a-pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })

                const result2 = await executor.execute(invocation2)
                expect(result2.finished).toBe(true)
                expect(result2.metrics.map((m) => m.metric_name)).toEqual(['early_exit'])
                expect(result2.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                    [
                      "Workflow exited early due to exit condition: exit_on_trigger_not_matched (Person no longer matches trigger filters)",
                    ]
                `)
            })

            it('should exit early if exit condition is exit_on_trigger_not_matched_or_conversion', async () => {
                // Setup: exit if person no longer matches trigger filters or conversion event is seen
                hogFlow.exit_condition = 'exit_on_trigger_not_matched_or_conversion'
                hogFlow.trigger = {
                    type: 'event',
                    filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                }
                hogFlow.conversion = {
                    window_minutes: 10,
                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
                }

                // Simulate person data changing so they no longer match the trigger filter
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$not-a-pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })

                const result1 = await executor.execute(invocation)
                expect(result1.finished).toBe(true)
                expect(result1.metrics.map((m) => m.metric_name)).toEqual(['succeeded', 'succeeded'])

                const invocation2 = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })

                const result2 = await executor.execute(invocation2)
                expect(result2.finished).toBe(true)
                expect(result2.metrics.map((m) => m.metric_name)).toEqual(['early_exit'])
                expect(result2.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                    [
                      "Workflow exited early due to exit condition: exit_on_trigger_not_matched_or_conversion (Person matches conversion filters)",
                    ]
                `)
            })

            describe('on_error handling', () => {
                let hogFlow: HogFlow
                beforeEach(async () => {
                    hogFlow = new FixtureHogFlowBuilder()
                        .withWorkflow({
                            actions: {
                                trigger: {
                                    type: 'trigger',
                                    config: {
                                        type: 'event',
                                        filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                                    },
                                },
                                function_id_1: {
                                    type: 'function',
                                    config: {
                                        template_id: 'template-test-hogflow-executor',
                                        inputs: {
                                            name: {
                                                value: `Mr {event?.properties?.name}`,
                                                bytecode: await compileHog(`raise Exception('fail!')`),
                                            },
                                        },
                                    },
                                    // filters: none
                                },
                                exit: {
                                    type: 'exit',
                                    config: {},
                                },
                            },
                            edges: [
                                { from: 'trigger', to: 'function_id_1', type: 'continue' },
                                { from: 'function_id_1', to: 'exit', type: 'continue' },
                            ],
                        })
                        .build()
                })

                it('should continue to next action if on_error is continue', async () => {
                    // Set on_error: 'continue' for function_id_1
                    const action = hogFlow.actions.find((a) => a.id === 'function_id_1')!
                    action.on_error = 'continue'

                    const invocation = createExampleHogFlowInvocation(hogFlow, {
                        event: {
                            ...createHogExecutionGlobals().event,
                            properties: { name: 'Error User' },
                        },
                    })

                    const result = await executor.execute(invocation)
                    expect(result.finished).toBe(true)
                    // Should move to exit action after error
                    expect(result.invocation.state.currentAction?.id).toBe('exit')
                    // Should log error and continuation
                    expect(result.logs.map((l) => l.message)).toEqual(
                        expect.arrayContaining([
                            expect.stringContaining('Could not execute bytecode for input field: name'),
                            expect.stringContaining('Continuing to next action'),
                            expect.stringContaining('Workflow moved to action [Action:exit]'),
                            expect.stringContaining('Workflow completed'),
                        ])
                    )
                    // Should track failed and succeeded metrics
                    expect(result.metrics.find((m) => m.instance_id === 'function_id_1')).toMatchObject({
                        metric_kind: 'failure',
                        metric_name: 'failed',
                    })
                    expect(result.metrics.find((m) => m.instance_id === 'exit')).toMatchObject({
                        metric_kind: 'success',
                        metric_name: 'succeeded',
                    })
                })

                it('should abort workflow if on_error is abort', async () => {
                    // Set on_error: 'abort' for function_id_1
                    const action = hogFlow.actions.find((a) => a.id === 'function_id_1')!
                    action.on_error = 'abort'

                    const invocation = createExampleHogFlowInvocation(hogFlow, {
                        event: {
                            ...createHogExecutionGlobals().event,
                            properties: { name: 'Error User' },
                        },
                    })

                    const result = await executor.execute(invocation)
                    expect(result.finished).toBe(true)
                    // Should NOT move to exit action, should stay on function_id_1
                    expect(result.invocation.state.currentAction?.id).toBe('function_id_1')
                    // Should log error and abort
                    expect(result.logs.map((l) => l.message)).toEqual(
                        expect.arrayContaining([
                            expect.stringContaining('Could not execute bytecode for input field: name'),
                            expect.stringContaining('Workflow encountered an error:'),
                            expect.stringContaining("Workflow is aborting due to the action's error handling setting"),
                        ])
                    )
                    // Should track failed metric only
                    expect(result.metrics.find((m) => m.instance_id === 'function_id_1')).toMatchObject({
                        metric_kind: 'failure',
                        metric_name: 'failed',
                    })
                    // Should not have succeeded metric for exit
                    expect(result.metrics.find((m) => m.instance_id === 'exit')).toBeUndefined()
                })
            })
        })

        describe('per action runner tests', () => {
            // NOTE: We test one case of each action to ensure it works as expected, the rest is handles as per-action unit test
            const cases: [
                string,
                SimpleHogFlowRepresentation,
                {
                    finished: boolean
                    scheduledAt?: DateTime
                    nextActionId: string
                },
            ][] = [
                [
                    'wait_until_condition',
                    {
                        actions: {
                            wait_until_condition: {
                                type: 'wait_until_condition',
                                config: {
                                    condition: {
                                        filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters, // no match
                                    },
                                    max_wait_duration: '10m',
                                },
                            },
                        },
                        edges: [
                            {
                                from: 'trigger',
                                to: 'wait_until_condition',
                                type: 'continue',
                            },
                        ],
                    },
                    {
                        finished: false,
                        scheduledAt: DateTime.fromISO('2025-01-01T00:10:00.000Z').toUTC(),
                        nextActionId: 'wait_until_condition',
                    },
                ],

                [
                    'conditional_branch',
                    {
                        actions: {
                            conditional_branch: {
                                type: 'conditional_branch',
                                config: {
                                    conditions: [
                                        {
                                            filters: HOG_FILTERS_EXAMPLES.elements_text_filter.filters,
                                        },
                                        {
                                            filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
                                        },
                                    ],
                                },
                            },
                        },
                        edges: [
                            {
                                from: 'conditional_branch',
                                to: 'exit',
                                type: 'branch',
                                index: 0,
                            },
                            {
                                from: 'conditional_branch',
                                to: 'delay',
                                type: 'branch',
                                index: 1,
                            },
                        ],
                    },
                    {
                        finished: false,
                        nextActionId: 'delay',
                    },
                ],
                [
                    'delay',
                    {
                        actions: {
                            delay: {
                                type: 'delay',
                                config: {
                                    delay_duration: '2h',
                                },
                            },
                        },
                        edges: [
                            {
                                from: 'delay',
                                to: 'exit',
                                type: 'continue',
                            },
                        ],
                    },
                    {
                        finished: false,
                        scheduledAt: DateTime.fromISO('2025-01-01T02:00:00.000Z').toUTC(),
                        nextActionId: 'exit',
                    },
                ],
                [
                    'random_cohort_branch',
                    {
                        actions: {
                            random_cohort_branch: {
                                type: 'random_cohort_branch',
                                config: {
                                    cohorts: [
                                        {
                                            percentage: 50,
                                        },
                                        {
                                            percentage: 50,
                                        },
                                    ],
                                },
                            },
                        },
                        edges: [
                            {
                                from: 'random_cohort_branch',
                                to: 'exit',
                                type: 'branch',
                                index: 0,
                            },
                            {
                                from: 'random_cohort_branch',
                                to: 'delay',
                                type: 'branch',
                                index: 1,
                            },
                        ],
                    },
                    {
                        finished: false,
                        nextActionId: 'delay',
                    },
                ],
                [
                    'exit',
                    {
                        actions: {
                            exit: {
                                type: 'exit',
                                config: {},
                            },
                        },
                        edges: [
                            {
                                from: 'exit',
                                to: 'exit',
                                type: 'continue',
                            },
                        ],
                    },
                    { finished: true, nextActionId: 'exit' },
                ],
            ]

            it.each(cases)(
                'should run %s action',
                async (actionId, simpleFlow, { nextActionId, finished, scheduledAt }) => {
                    const hogFlow = createHogFlow(simpleFlow)
                    const invocation = createExampleHogFlowInvocation(hogFlow, {
                        event: {
                            ...createHogExecutionGlobals().event,
                            event: '$pageview',
                            properties: {
                                $current_url: 'https://posthog.com',
                            },
                        },
                    })

                    // For the random_cohort_branch action
                    jest.spyOn(Math, 'random').mockReturnValue(0.8)

                    invocation.state.currentAction = {
                        id: actionId,
                        startedAtTimestamp: DateTime.utc().toMillis(),
                    }

                    const result = await executor['executeCurrentAction'](invocation)

                    expect(result.finished).toEqual(finished)
                    expect(result.invocation.queueScheduledAt).toEqual(scheduledAt)
                    expect(result.invocation.state.currentAction!.id).toEqual(nextActionId)
                }
            )
        })

        describe('capturedPostHogEvents', () => {
            it('should collect capturedPostHogEvents from hog function actions', async () => {
                const hogFlow = createHogFlow({
                    actions: {
                        capture_function: {
                            type: 'function',
                            config: {
                                template_id: 'template-posthog-capture',
                                inputs: {
                                    event: { value: 'custom_event' },
                                    distinct_id: { value: '{event.distinct_id}' },
                                    properties: {
                                        value: {
                                            user: '{event.properties.user_name}',
                                            value: '{event.properties.value}',
                                        },
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
                            to: 'capture_function',
                            type: 'continue',
                        },
                        {
                            from: 'capture_function',
                            to: 'exit',
                            type: 'continue',
                        },
                    ],
                })

                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        properties: { user_name: 'Test User', value: 'test-value-123' },
                    },
                })

                const result = await executor.execute(invocation)

                expect(result.finished).toBe(true)
                expect(result.error).toBeUndefined()

                expect(result.capturedPostHogEvents).toBeDefined()
                expect(result.capturedPostHogEvents).toHaveLength(1)
                expect(result.capturedPostHogEvents[0]).toMatchObject({
                    team_id: 1,
                    event: 'custom_event',
                    distinct_id: '{event.distinct_id}',
                    properties: {
                        user: '{event.properties.user_name}',
                        value: '{event.properties.value}',
                    },
                })
            })

            it('should collect capturedPostHogEvents from multiple hog function actions', async () => {
                const hogFlow = createHogFlow({
                    actions: {
                        capture_function_1: {
                            type: 'function',
                            config: {
                                template_id: 'template-posthog-capture',
                                inputs: {
                                    event: { value: 'custom_event' },
                                    distinct_id: { value: 'user1' },
                                    properties: { value: { user: 'User1', value: 'value1' } },
                                },
                            },
                        },
                        capture_function_2: {
                            type: 'function',
                            config: {
                                template_id: 'template-posthog-capture',
                                inputs: {
                                    event: { value: 'custom_event' },
                                    distinct_id: { value: 'user2' },
                                    properties: { value: { user: 'User2', value: 'value2' } },
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
                            to: 'capture_function_1',
                            type: 'continue',
                        },
                        {
                            from: 'capture_function_1',
                            to: 'capture_function_2',
                            type: 'continue',
                        },
                        {
                            from: 'capture_function_2',
                            to: 'exit',
                            type: 'continue',
                        },
                    ],
                })

                const invocation = createExampleHogFlowInvocation(hogFlow)

                const result = await executor.execute(invocation)

                expect(result.finished).toBe(true)
                expect(result.error).toBeUndefined()

                expect(result.capturedPostHogEvents).toHaveLength(2)
                expect(result.capturedPostHogEvents[0]).toMatchObject({
                    event: 'custom_event',
                    distinct_id: 'user1',
                    properties: { user: 'User1', value: 'value1' },
                })
                expect(result.capturedPostHogEvents[1]).toMatchObject({
                    event: 'custom_event',
                    distinct_id: 'user2',
                    properties: { user: 'User2', value: 'value2' },
                })
            })
        })
    })

    describe('variable merging', () => {
        it('merges default and provided variables correctly', () => {
            const hogFlow: HogFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: {
                                type: 'event',
                                filters: {},
                            },
                        },

                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [{ from: 'trigger', to: 'exit', type: 'continue' }],
                })
                .build()

            // Set variables directly with required fields
            hogFlow.variables = [
                { key: 'foo', default: 'bar', type: 'string', label: 'foo' },
                { key: 'baz', default: 123, type: 'number', label: 'baz' },
                { key: 'overrideMe', default: 'defaultValue', type: 'string', label: 'overrideMe' },
            ]

            const globals = {
                event: {
                    event: 'test',
                    properties: {},
                    url: '',
                    distinct_id: '',
                    timestamp: '',
                    uuid: '',
                    elements_chain: '',
                },
                person: { id: 'person_id', name: '', properties: {}, url: '' },
                variables: {
                    overrideMe: 'customValue',
                    extra: 'shouldBeIncluded',
                },
            }
            const filterGlobals = createHogExecutionGlobals()
            const invocation = require('./hogflow-executor.service').createHogFlowInvocation(
                globals,
                hogFlow,
                filterGlobals
            )
            expect(invocation.state.variables).toEqual({
                foo: 'bar',
                baz: 123,
                overrideMe: 'customValue',
                extra: 'shouldBeIncluded',
            })
        })
    })
})
