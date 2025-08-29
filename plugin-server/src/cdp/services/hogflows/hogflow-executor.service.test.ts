// sort-imports-ignore
import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from '~/cdp/_tests/builders/hogflow.builder'
import { createHogExecutionGlobals, insertHogFunctionTemplate } from '~/cdp/_tests/fixtures'
import { compileHog } from '~/cdp/templates/compiler'
import { HogFlow } from '~/schema/hogflow'
import { resetTestDatabase } from '~/tests/helpers/sql'

import { Hub } from '../../../types'
import { createHub } from '../../../utils/db/hub'
import { HOG_FILTERS_EXAMPLES } from '../../_tests/examples'
import { createExampleHogFlowInvocation } from '../../_tests/fixtures-hogflows'
import { HogExecutorService } from '../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { HogFlowExecutorService } from './hogflow-executor.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { RecipientPreferencesService } from '../messaging/recipient-preferences.service'
import { fetch } from '~/utils/request'

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
        const recipientsManager = new RecipientsManagerService(hub)
        const recipientPreferencesService = new RecipientPreferencesService(recipientsManager)

        const exampleHog = `
            print(f'Hello, {inputs.name}!')
            print('Fetch 1', fetch('https://posthog.com').status)`

        await insertHogFunctionTemplate(hub.postgres, {
            id: 'template-test-hogflow-executor',
            name: 'Test Template',
            code: exampleHog,
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
            code: exampleHogMultiFetch,
            inputs_schema: [
                {
                    key: 'name',
                    type: 'string',
                    required: true,
                },
            ],
            bytecode: await compileHog(exampleHogMultiFetch),
        })

        executor = new HogFlowExecutorService(hub, hogExecutor, hogFunctionTemplateManager, recipientPreferencesService)
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

        it('executes only a single step at a time in debugMode', async () => {
            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    properties: {
                        name: 'Debug User',
                    },
                },
            })
            invocation.debugMode = true

            // First step: should process trigger and move to function_id_1, but not complete
            const result1 = await executor.execute(invocation)
            expect(result1.finished).toBe(false)
            expect(result1.invocation.state.currentAction.id).toBe('function_id_1')
            expect(result1.logs.some((log) => log.message.includes("Workflow moved to action 'function_id_1"))).toBe(true)

            // Second step: should process function_id_1 and move to exit, but not complete
            const result2 = await executor.execute(result1.invocation)
            expect(result2.finished).toBe(false)
            expect(result2.invocation.state.currentAction.id).toBe('exit')
            expect(result2.logs.some((log) => log.message.includes("Workflow moved to action 'exit"))).toBe(true)
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
            expect(result.invocation.state.currentAction!.hogFunctionState).toEqual(expect.any(Object))
            expect(result.invocation.queueScheduledAt).toEqual(expect.any(DateTime))
            expect(result.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
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
                  "[Action:function_id_1] Fetch 2, 200",
                  "Workflow will pause until 2025-01-01T00:00:00.000Z",
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
                                filters: HOG_FILTERS_EXAMPLES.no_filters.filters,
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
            it ('should not exit early if exit condition is exit_only_at_end', async() => {
                // Setup: exit if person no longer matches trigger filters
                const hogFlow = new FixtureHogFlowBuilder()
                    .withExitCondition('exit_only_at_end')
                    .withWorkflow({
                        actions: {
                            trigger: {
                                type: 'trigger',
                                config: {
                                    type: 'event',
                                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
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

                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })
                invocation.debugMode = true

                // Step 1: run first action (function_id_1)
                const result1 = await executor.execute(invocation)
                expect(result1.finished).toBe(false)
                expect(
                    result1.metrics.some((m) => m.instance_id === 'function_id_1' && m.metric_name === 'succeeded')
                ).toBe(true)

                // Simulate person data changing so they no longer match the trigger filter
                const origPerson = result1.invocation.person || { id: 'person_id', name: '', properties: {}, url: '' }
                const origState = result1.invocation.state
                const origEvent = origState.event
                const invocation2 = {
                    ...result1.invocation,
                    person: {
                        ...origPerson,
                        properties: { ...origPerson.properties, $current_url: undefined },
                    },
                    state: {
                        ...origState,
                        event: {
                            ...origEvent,
                            event: 'not-a-pageview',
                        },
                        currentAction: { id: 'exit', startedAtTimestamp: DateTime.now().toMillis() },
                    },
                }

                // Step 2: run again, should NOT exit early due to exit_only_at_end
                const result2 = await executor.execute(invocation2 as any)
                expect(result2.finished).toBe(true)
                expect(
                    result2.logs.some((log) =>
                        log.message.includes('Workflow exited early due to exit condition')
                    )
                ).toBe(false)
                expect(result2.metrics.some((metric) => metric.metric_name === 'filtered')).toBe(false)
            })

            it('should exit early if exit condition is exit_on_conversion', async () => {
                // Setup: exit if conversion event is seen
                const hogFlow = new FixtureHogFlowBuilder()
                    .withExitCondition('exit_on_conversion')
                    .withWorkflow({
                        actions: {
                            trigger: {
                                type: 'trigger',
                                config: {
                                    type: 'event',
                                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
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

                // Simulate a conversion event
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com', conversion: true },
                    },
                })
                invocation.debugMode = true

                // Step 1: run first action (function_id_1)
                const result1 = await executor.execute(invocation)
                expect(result1.finished).toBe(false)

                // Simulate conversion detected (implementation may vary, adjust as needed)
                const origPerson = result1.invocation.person || { id: 'person_id', name: '', properties: {}, url: '' }
                const origState = result1.invocation.state
                const origEvent = origState.event
                const invocation2 = {
                    ...result1.invocation,
                    person: origPerson,
                    state: {
                        ...origState,
                        event: {
                            ...origEvent,
                            properties: { ...origEvent.properties, conversion: true },
                        },
                        currentAction: { id: 'exit', startedAtTimestamp: DateTime.now().toMillis() },
                    },
                }

                // Step 2: run again, should exit early due to conversion
                const result2 = await executor.execute(invocation2 as any)
                expect(result2.finished).toBe(true)
                expect(
                    result2.logs.some((log) =>
                        log.message.includes('Workflow exited early due to exit condition')
                    )
                ).toBe(true)
            })

            it('should exit early if exit condition is exit_on_trigger_not_matched', async () => {
                // Setup: exit if person no longer matches trigger filters
                const hogFlow = new FixtureHogFlowBuilder()
                    .withExitCondition('exit_on_trigger_not_matched')
                    .withWorkflow({
                        actions: {
                            trigger: {
                                type: 'trigger',
                                config: {
                                    type: 'event',
                                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
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

                // Step 1: event matches trigger filters
                const invocation1 = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })
                invocation1.debugMode = true

                const result1 = await executor.execute(invocation1)
                expect(result1.finished).toBe(false)
                // Should NOT exit early on first invocation
                expect(
                    result1.logs.some((log) =>
                        log.message.includes('Workflow exited early due to exit condition')
                    )
                ).toBe(false)

                // Step 2: event does NOT match trigger filters
                const origPerson = result1.invocation.person || { id: 'person_id', name: '', properties: {}, url: '' }
                const origState = result1.invocation.state
                const origEvent = origState.event
                const invocation2 = {
                    ...result1.invocation,
                    person: {
                        ...origPerson,
                        properties: { ...origPerson.properties, $current_url: undefined },
                    },
                    state: {
                        ...origState,
                        event: {
                            ...origEvent,
                            event: 'not-a-pageview',
                        },
                        currentAction: { id: 'exit', startedAtTimestamp: DateTime.now().toMillis() },
                    },
                }

                const result2 = await executor.execute(invocation2 as any)
                expect(result2.finished).toBe(true)
                expect(
                    result2.logs.some((log) =>
                        log.message.includes('Workflow exited early due to exit condition')
                    )
                ).toBe(true)
                expect(result2.metrics.some((metric) => metric.metric_name === 'filtered')).toBe(true)
            })

            it('should exit early if exit condition is exit_on_trigger_not_matched_or_conversion', async () => {
                // Setup: exit if person no longer matches trigger filters or conversion event is seen
                const hogFlow = new FixtureHogFlowBuilder()
                    .withExitCondition('exit_on_trigger_not_matched_or_conversion')
                    .withWorkflow({
                        actions: {
                            trigger: {
                                type: 'trigger',
                                config: {
                                    type: 'event',
                                    filters: HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter.filters,
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

                // Simulate person data changing so they no longer match the trigger filter
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })
                invocation.debugMode = true

                // Step 1: run first action (function_id_1)
                const result1 = await executor.execute(invocation)
                expect(result1.finished).toBe(false)

                // Simulate trigger not matched
                const origPerson = result1.invocation.person || { id: 'person_id', name: '', properties: {}, url: '' }
                const origState = result1.invocation.state
                const origEvent = origState.event
                const invocation2 = {
                    ...result1.invocation,
                    person: {
                        ...origPerson,
                        properties: { ...origPerson.properties, $current_url: undefined },
                    },
                    state: {
                        ...origState,
                        event: {
                            ...origEvent,
                            event: 'not-a-pageview',
                        },
                        currentAction: { id: 'exit', startedAtTimestamp: DateTime.now().toMillis() },
                    },
                }

                // Step 2: run again, should exit early due to trigger not matched
                const result2 = await executor.execute(invocation2 as any)
                expect(result2.finished).toBe(true)
                expect(
                    result2.logs.some((log) =>
                        log.message.includes('Workflow exited early due to exit condition')
                    )
                ).toBe(true)
                expect(result2.metrics.some((metric) => metric.metric_name === 'filtered')).toBe(true)

                // Simulate conversion event (should also exit early)
                const invocation3 = {
                    ...result1.invocation,
                    person: origPerson,
                    state: {
                        ...origState,
                        event: {
                            ...origEvent,
                            properties: { ...origEvent.properties, conversion: true },
                        },
                        currentAction: { id: 'exit', startedAtTimestamp: DateTime.now().toMillis() },
                    },
                }
                const result3 = await executor.execute(invocation3 as any)
                expect(result3.finished).toBe(true)
                expect(
                    result3.logs.some((log) =>
                        log.message.includes('Workflow exited early due to exit condition')
                    )
                ).toBe(true)
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
    })
})
