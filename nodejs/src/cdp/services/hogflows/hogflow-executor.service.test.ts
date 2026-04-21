// sort-imports-ignore
import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from '~/cdp/_tests/builders/hogflow.builder'
import { createHogExecutionGlobals, insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { compileHog } from '~/cdp/templates/compiler'
import { template as posthogCaptureTemplate } from '~/cdp/templates/_destinations/posthog_capture/posthog-capture.template'
import { HogFlow } from '~/schema/hogflow'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { fetch } from '~/utils/request'
import { logger } from '../../../utils/logger'
import { Hub } from '../../../types'
import { createHub } from '../../../utils/db/hub'
import { HOG_FILTERS_EXAMPLES } from '../../_tests/examples'
import { createExampleHogFlowInvocation } from '../../_tests/fixtures-hogflows'
import { HogExecutorService } from '../hog-executor.service'
import { HogInputsService } from '../hog-inputs.service'
import { EmailService } from '../messaging/email.service'
import { RecipientTokensService } from '../messaging/recipient-tokens.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { RecipientPreferencesService } from '../messaging/recipient-preferences.service'
import { HogFlowExecutorService, createHogFlowInvocation } from './hogflow-executor.service'
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
        const hogInputsService = new HogInputsService(hub.integrationManager, hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        const emailService = new EmailService(
            {
                sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                sesRegion: hub.SES_REGION,
                sesEndpoint: hub.SES_ENDPOINT,
            },
            hub.integrationManager,
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL
        )
        const recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        const hogExecutor = new HogExecutorService(
            {
                hogCostTimingUpperMs: hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                googleAdwordsDeveloperToken: hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN,
                fetchRetries: hub.CDP_FETCH_RETRIES,
                fetchBackoffBaseMs: hub.CDP_FETCH_BACKOFF_BASE_MS,
                fetchBackoffMaxMs: hub.CDP_FETCH_BACKOFF_MAX_MS,
            },
            { teamManager: hub.teamManager, siteUrl: hub.SITE_URL },
            hogInputsService,
            emailService,
            recipientTokensService
        )
        const hogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub.postgres)
        const hogFlowFunctionsService = new HogFlowFunctionsService(
            hub.SITE_URL,
            hogFunctionTemplateManager,
            hogExecutor
        )
        const recipientsManager = new RecipientsManagerService(hub.postgres)
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
                    timestamp: '2026-01-30T20:20:20.200Z',
                },
            })

            const result = await executor.execute(invocation)

            expect(result).toEqual({
                capturedPostHogEvents: [],
                warehouseWebhookPayloads: [],
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
                        name: 'John Doe',
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
                        message:
                            'Starting workflow execution at trigger for [Person:person_id|John Doe] on [Event:uuid|test|2026-01-30T20:20:20.200Z]',
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
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        count: 1,
                    },
                    {
                        team_id: hogFlow.team_id,
                        app_source_id: hogFlow.id,
                        instance_id: 'function_id_1',
                        metric_kind: 'fetch',
                        metric_name: 'billable_invocation',
                        count: 1,
                    },
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
                    timestamp: '2026-01-30T20:20:20.200Z',
                },
            })

            const result = await executor.execute(invocation)

            expect(result.finished).toEqual(false)
            expect(result.invocation.state.currentAction!.hogFunctionState).toEqual(expect.any(Object))
            expect(result.invocation.queueScheduledAt).toEqual(expect.any(DateTime))
            expect(result.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                [
                  "Starting workflow execution at trigger for [Person:person_id|John Doe] on [Event:uuid|test|2026-01-30T20:20:20.200Z]",
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
                  "Resuming workflow execution at [Action:function_id_1] on [Event:uuid|test|2026-01-30T20:20:20.200Z]",
                  "Executing action [Action:function_id_1]",
                  "[Action:function_id_1] Fetch 2, 200",
                  "Workflow will pause until 2025-01-01T00:00:00.000Z",
                ]
            `)

            const result3 = await executor.execute(result2.invocation)

            expect(result3.finished).toEqual(true)
            expect(cleanLogs(result3.logs.map((log) => log.message))).toMatchInlineSnapshot(`
                [
                  "Resuming workflow execution at [Action:function_id_1] on [Event:uuid|test|2026-01-30T20:20:20.200Z]",
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
                expect(
                    result.metrics.find((x) => x.instance_id === 'function_id_1' && x.metric_name === 'succeeded')
                ).toMatchObject({
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
                        timestamp: '2026-01-30T20:20:20.200Z',
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
                    'Resuming workflow execution at [Action:function_id_1] on [Event:uuid|test|2026-01-30T20:20:20.200Z]',
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
                // Metrics: 'fetch' from function_id_1, 'billable_invocation' from function_id_1, 'succeeded' from function_id_1, 'succeeded' from exit action
                expect(result1.metrics.map((m) => m.metric_name)).toEqual([
                    'fetch',
                    'billable_invocation',
                    'succeeded',
                    'succeeded',
                ])

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
                // Metrics: 'fetch' from function_id_1, 'billable_invocation' from function_id_1, 'succeeded' from function_id_1, 'succeeded' from exit action
                expect(result2.metrics.map((m) => m.metric_name)).toEqual([
                    'fetch',
                    'billable_invocation',
                    'succeeded',
                    'succeeded',
                ])
            })

            it('should exit early if exit condition is exit_on_conversion', async () => {
                hogFlow.exit_condition = 'exit_on_conversion'
                hogFlow.conversion = {
                    filters: [
                        {
                            key: '$browser',
                            type: 'person',
                            value: ['Chrome'],
                            operator: 'exact',
                        },
                    ],
                    bytecode: ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 32, 'person', 1, 3, 11],
                    window_minutes: null,
                }

                // Person does not match conversion filters yet
                const invocation = createExampleHogFlowInvocation(
                    hogFlow,
                    {
                        event: {
                            ...createHogExecutionGlobals().event,
                            event: '$pageview',
                            properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                        },
                    },
                    {
                        properties: {
                            $browser: 'Firefox',
                        },
                    }
                )

                const result1 = await executor.execute(invocation)
                expect(result1.finished).toBe(true)
                // Metrics: 'fetch' from function_id_1, 'billable_invocation' from function_id_1, 'succeeded' from function_id_1, 'succeeded' from exit action
                expect(result1.metrics.map((m) => m.metric_name)).toEqual([
                    'fetch',
                    'billable_invocation',
                    'succeeded',
                    'succeeded',
                ])

                const invocation2 = createExampleHogFlowInvocation(
                    hogFlow,
                    {
                        event: {
                            ...createHogExecutionGlobals().event,
                            event: '$pageview',
                            properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                        },
                    },
                    {
                        properties: {
                            $browser: 'Chrome',
                        },
                    }
                )
                const result2 = await executor.execute(invocation2)
                expect(result2.finished).toBe(true)
                expect(result2.metrics.map((m) => m.metric_name)).toEqual(['early_exit'])
                expect(result2.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                    [
                      "Workflow exited early due to exit condition: exit_on_conversion ([Person:person_id|John Doe] matches conversion filters)",
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
                expect(result1.metrics.map((m) => m.metric_name)).toEqual([
                    'fetch',
                    'billable_invocation',
                    'succeeded',
                    'succeeded',
                ])

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
                      "Workflow exited early due to exit condition: exit_on_trigger_not_matched ([Person:person_id|John Doe] no longer matches trigger filters)",
                    ]
                `)
            })

            it('should exit early if exit condition is exit_on_trigger_not_matched_or_conversion', async () => {
                // Setup: exit if person no longer matches trigger filters or person matches conversion filters
                hogFlow.exit_condition = 'exit_on_trigger_not_matched_or_conversion'
                hogFlow.trigger = {
                    type: 'event',
                    filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                }
                hogFlow.conversion = {
                    filters: [
                        {
                            key: '$browser',
                            type: 'person',
                            value: ['Chrome'],
                            operator: 'exact',
                        },
                    ],
                    bytecode: ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 32, 'person', 1, 3, 11],
                    window_minutes: null,
                }

                // Person does not match conversion filters yet
                const invocation = createExampleHogFlowInvocation(
                    hogFlow,
                    {
                        event: {
                            ...createHogExecutionGlobals().event,
                            event: '$not-a-pageview',
                            properties: { $current_url: 'https://posthog.com' },
                        },
                    },
                    {
                        properties: {
                            $browser: 'Firefox',
                        },
                    }
                )

                const result1 = await executor.execute(invocation)
                expect(result1.finished).toBe(true)
                // Metrics: 'fetch' from function_id_1, 'billable_invocation' from function_id_1, 'succeeded' from function_id_1, 'succeeded' from exit action
                expect(result1.metrics.map((m) => m.metric_name)).toEqual([
                    'fetch',
                    'billable_invocation',
                    'succeeded',
                    'succeeded',
                ])

                const invocation2 = createExampleHogFlowInvocation(
                    hogFlow,
                    {
                        event: {
                            ...createHogExecutionGlobals().event,
                            event: '$not-a-pageview',
                            properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                        },
                    },
                    {
                        properties: {
                            $browser: 'Chrome',
                        },
                    }
                )

                const result2 = await executor.execute(invocation2)
                expect(result2.finished).toBe(true)
                expect(result2.metrics.map((m) => m.metric_name)).toEqual(['early_exit'])
                expect(result2.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                    [
                      "Workflow exited early due to exit condition: exit_on_trigger_not_matched_or_conversion ([Person:person_id|John Doe] matches conversion filters)",
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
                                middle_action: {
                                    id: 'middle_action',
                                    name: 'Middle Action',
                                    description: '',
                                    type: 'delay',
                                    config: { delay_duration: '5m' },
                                    created_at: new Date().getUTCSeconds(),
                                    updated_at: new Date().getUTCSeconds(),
                                },
                                exit: {
                                    type: 'exit',
                                    config: {},
                                },
                            },
                            edges: [
                                { from: 'trigger', to: 'function_id_1', type: 'continue' },
                                { from: 'function_id_1', to: 'middle_action', type: 'continue' },
                                { from: 'middle_action', to: 'exit', type: 'continue' },
                            ],
                        })
                        .build()
                })

                describe('execute error handling when error is returned, not thrown', () => {
                    it('continues to next action when on_error is continue', async () => {
                        const action = hogFlow.actions.find((a) => a.id === 'function_id_1')!
                        action.on_error = 'continue'

                        // Mock the handler to return an error in the result
                        const functionHandler = executor['actionHandlers']['function']
                        jest.spyOn(functionHandler, 'execute').mockResolvedValueOnce({
                            error: new Error('Mocked handler error'),
                        })

                        const invocation = createExampleHogFlowInvocation(hogFlow, {
                            event: {
                                ...createHogExecutionGlobals().event,
                                properties: { name: 'Test User' },
                            },
                        })
                        invocation.state.currentAction = {
                            id: 'function_id_1',
                            startedAtTimestamp: DateTime.now().toMillis(),
                        }

                        const result = await executor.executeCurrentAction(invocation)

                        expect(result.error).toBe('Mocked handler error')

                        expect(result.finished).toBe(false)

                        expect(result.invocation.state.currentAction?.id).toBe('middle_action')
                        expect(result.logs.map((l) => l.message)).toEqual(
                            expect.arrayContaining([
                                expect.stringContaining('Continuing to next action'),
                                expect.stringContaining('Workflow moved to action [Action:middle_action]'),
                            ])
                        )
                    })

                    it('does NOT continue to next action when on_error is abort', async () => {
                        const action = hogFlow.actions.find((a) => a.id === 'function_id_1')!
                        action.on_error = 'abort'

                        // Mock the handler to return an error in the result
                        const functionHandler = executor['actionHandlers']['function']
                        jest.spyOn(functionHandler, 'execute').mockResolvedValueOnce({
                            error: new Error('Mocked handler error'),
                        })

                        const invocation = createExampleHogFlowInvocation(hogFlow, {
                            event: {
                                ...createHogExecutionGlobals().event,
                                properties: { name: 'Test User' },
                            },
                        })
                        invocation.state.currentAction = {
                            id: 'function_id_1',
                            startedAtTimestamp: DateTime.now().toMillis(),
                        }

                        const loggerErrorSpy = jest.spyOn(logger, 'error')

                        const result = await executor.execute(invocation)

                        expect(result.error).toBe('Mocked handler error')
                        expect(result.finished).toBe(true)
                        // Should stay on function_id_1 - goToNextAction was NOT called
                        expect(result.invocation.state.currentAction?.id).toBe('function_id_1')
                        expect(result.logs.map((l) => l.message)).not.toEqual(
                            expect.arrayContaining([expect.stringContaining('Workflow moved to action')])
                        )
                        expect(result.logs.map((l) => l.message)).toEqual(
                            expect.arrayContaining([
                                expect.stringContaining(
                                    `Workflow is aborting due to [Action:function_id_1] error handling setting being set to abort on error`
                                ),
                            ])
                        )

                        // Check that logger.error was called with the expected log
                        expect(loggerErrorSpy).toHaveBeenCalledWith(
                            '🦔',
                            expect.stringContaining(
                                `[HogFlowExecutor] Error executing hog flow ${hogFlow.id} - ${hogFlow.name}. Event: '`
                            ),
                            expect.any(Error)
                        )
                        loggerErrorSpy.mockRestore()
                    })
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

    describe('filter_test_accounts', () => {
        let hogFlow: HogFlow

        beforeEach(async () => {
            hogFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: {
                                type: 'event',
                                // Use the test account filter which filters out @posthog.com emails
                                filters: HOG_FILTERS_EXAMPLES.test_account_filter.filters ?? {},
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

        it('should filter out internal users with @posthog.com email', async () => {
            // Create globals with internal user email
            const globals = createHogExecutionGlobals({
                event: {
                    uuid: 'uuid',
                    event: '$pageview',
                    distinct_id: 'distinct_id',
                    elements_chain: '',
                    timestamp: new Date().toISOString(),
                    url: 'http://localhost:8000/events/1',
                    properties: {
                        name: 'Internal User',
                    },
                },
                person: {
                    id: 'person_internal',
                    name: 'Internal User',
                    url: '',
                    properties: {
                        email: 'internal@posthog.com',
                    },
                },
            })

            const result = await executor.buildHogFlowInvocations([hogFlow], globals)

            // Should not match because email contains @posthog.com
            expect(result.invocations).toHaveLength(0)
        })

        it('should allow external users without @posthog.com email', async () => {
            // Create globals with external user email
            const globals = createHogExecutionGlobals({
                event: {
                    uuid: 'uuid',
                    event: '$pageview',
                    distinct_id: 'distinct_id',
                    elements_chain: '',
                    timestamp: new Date().toISOString(),
                    url: 'http://localhost:8000/events/1',
                    properties: {
                        name: 'External User',
                    },
                },
                person: {
                    id: 'person_external',
                    name: 'External User',
                    url: '',
                    properties: {
                        email: 'external@customer.com',
                    },
                },
            })

            const result = await executor.buildHogFlowInvocations([hogFlow], globals)

            // Should match because email doesn't contain @posthog.com
            expect(result.invocations).toHaveLength(1)
            expect(result.invocations[0].hogFlow.id).toBe(hogFlow.id)
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
                project: { id: 1, name: 'Test Project', url: '' },
                person: { id: 'person_id', name: 'John Doe', properties: {}, url: '' },
                variables: {
                    overrideMe: 'customValue',
                    extra: 'shouldBeIncluded',
                },
            }
            const invocation = createHogFlowInvocation(globals, hogFlow, {} as any)
            expect(invocation.state.variables).toEqual({
                foo: 'bar',
                baz: 123,
                overrideMe: 'customValue',
                extra: 'shouldBeIncluded',
            })
        })
    })

    describe('output variable mapping', () => {
        let hogFlowBuilder: (outputVariable: any) => Promise<HogFlow>

        beforeEach(async () => {
            const nameBytecode = await compileHog(`return 'Test'`)
            hogFlowBuilder = (outputVariable: any) => {
                return Promise.resolve(
                    new FixtureHogFlowBuilder()
                        .withWorkflow({
                            actions: {
                                trigger: {
                                    type: 'trigger',
                                    config: {
                                        type: 'event',
                                        filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                                    },
                                },
                                action_1: {
                                    type: 'function',
                                    config: {
                                        template_id: 'template-test-hogflow-executor',
                                        inputs: {
                                            name: {
                                                value: 'Test',
                                                bytecode: nameBytecode,
                                            },
                                        },
                                    },
                                    output_variable: outputVariable,
                                } as any,
                                exit: {
                                    type: 'exit',
                                    config: {},
                                },
                            },
                            edges: [
                                { from: 'trigger', to: 'action_1', type: 'continue' },
                                { from: 'action_1', to: 'exit', type: 'continue' },
                            ],
                        })
                        .build()
                )
            }
        })

        const executeToCompletion = async (hogFlow: HogFlow) => {
            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    properties: { name: 'Test' },
                },
            })
            let result = await executor.execute(invocation)
            while (!result.finished) {
                result = await executor.execute(result.invocation)
            }
            return result
        }

        it('stores full result in variable with single object output_variable', async () => {
            const hogFlow = await hogFlowBuilder({ key: 'response', result_path: null })
            const result = await executeToCompletion(hogFlow)

            expect(result.invocation.state.variables?.response).toBeDefined()
            expect(result.invocation.state.variables?.response).toHaveProperty('status', 200)
        })

        it('stores extracted value via result_path', async () => {
            const hogFlow = await hogFlowBuilder({ key: 'http_status', result_path: 'status' })
            const result = await executeToCompletion(hogFlow)

            expect(result.invocation.state.variables).toEqual({ http_status: 200 })
        })

        it('stores multiple variables from array output_variable', async () => {
            const hogFlow = await hogFlowBuilder([
                { key: 'http_status', result_path: 'status' },
                { key: 'response_body', result_path: 'body' },
            ])
            const result = await executeToCompletion(hogFlow)

            expect(result.invocation.state.variables?.http_status).toBe(200)
            expect(result.invocation.state.variables?.response_body).toBeDefined()
        })

        it('spreads object result into prefixed variables', async () => {
            const hogFlow = await hogFlowBuilder({ key: 'resp', result_path: 'body', spread: true })
            const result = await executeToCompletion(hogFlow)

            // body is { status: 200 } so spread should create resp_status
            expect(result.invocation.state.variables?.resp_status).toBe(200)
        })

        it('skips entries with empty key in array form', async () => {
            const hogFlow = await hogFlowBuilder([
                { key: '', result_path: 'status' },
                { key: 'http_status', result_path: 'status' },
            ])
            const result = await executeToCompletion(hogFlow)

            expect(result.invocation.state.variables).toEqual({ http_status: 200 })
        })

        it('does nothing when output_variable is undefined', async () => {
            const hogFlow = await hogFlowBuilder(undefined)
            const result = await executeToCompletion(hogFlow)

            expect(result.invocation.state.variables).toBeUndefined()
        })

        it('errors and exits when total variable size exceeds 5KB with on_error=abort', async () => {
            const hogFlow = await hogFlowBuilder({ key: 'response', result_path: null })
            // Set action to abort on error
            const action = hogFlow.actions.find((a) => a.id === 'action_1')!
            action.on_error = 'abort'

            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    properties: { name: 'Test' },
                },
            })
            invocation.state.variables = { existing: 'x'.repeat(5100) }

            let result = await executor.execute(invocation)
            while (!result.finished) {
                result = await executor.execute(result.invocation)
            }

            expect(result.error).toContain('exceeds 5KB limit')
            expect(result.invocation.state.variables?.response).toBeUndefined()
            expect(result.invocation.state.variables?.existing).toBe('x'.repeat(5100))
        })

        it('errors but continues when total variable size exceeds 5KB with on_error=continue', async () => {
            const hogFlow = await hogFlowBuilder({ key: 'response', result_path: null })
            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    properties: { name: 'Test' },
                },
            })
            invocation.state.variables = { existing: 'x'.repeat(5100) }

            let result = await executor.execute(invocation)
            while (!result.finished) {
                result = await executor.execute(result.invocation)
            }

            // on_error=continue (default), so workflow finishes but variables are cleaned up
            expect(result.finished).toBe(true)
            expect(result.invocation.state.variables?.response).toBeUndefined()
            expect(result.invocation.state.variables?.existing).toBe('x'.repeat(5100))
            expect(result.logs.some((l) => l.message.includes('exceeds 5KB limit'))).toBe(true)
        })

        it('warns when output variable specified but no result returned', async () => {
            // Use a template that doesn't do a fetch (no result)
            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-no-result',
                name: 'No result template',
                code: `print('no result')`,
                inputs_schema: [],
            })

            const hogFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: {
                                type: 'event',
                                filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                            },
                        },
                        action_1: {
                            type: 'function',
                            config: {
                                template_id: 'template-no-result',
                                inputs: {},
                            },
                            output_variable: { key: 'my_var', result_path: null },
                        } as any,
                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [
                        { from: 'trigger', to: 'action_1', type: 'continue' },
                        { from: 'action_1', to: 'exit', type: 'continue' },
                    ],
                })
                .build()

            const result = await executeToCompletion(hogFlow)

            // No variables should be set since no result was produced
            expect(result.invocation.state.variables).toBeUndefined()
        })
    })

    describe('billing metrics', () => {
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
                        ...flow.actions,
                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [...flow.edges],
                })
                .build()
        }

        it('should record billing metrics for both regular hog functions and email functions', async () => {
            const team = await getFirstTeam(hub.postgres)

            await insertIntegration(hub.postgres, team.id, {
                id: 1,
                kind: 'email',
                config: {
                    email: 'test@posthog.com',
                    name: 'Test User',
                    domain: 'posthog.com',
                    verified: true,
                    provider: 'maildev',
                },
            })

            const regularTemplate = await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-email',
                name: 'Test Regular Template',
                code: `sendEmail(inputs.email)`,
                inputs_schema: [
                    {
                        type: 'native_email',
                        key: 'email',
                        label: 'Email message',
                        integration: 'email',
                        required: true,
                        default: {
                            to: {
                                email: '',
                                name: '',
                            },
                            from: {
                                email: '',
                                name: '',
                            },
                            replyTo: '',
                            subject: '',
                            preheader: '',
                            text: 'Hello from PostHog!',
                            html: '<div>Hi {{ person.properties.name }}, this email was sent from PostHog!</div>',
                        },
                        secret: false,
                        description: '',
                        templating: 'liquid',
                    },
                ],
            })

            // Create a workflow with 2 regular hog function actions and 2 email actions
            const hogFlow = createHogFlow({
                actions: {
                    function_1: {
                        type: 'function',
                        config: {
                            template_id: regularTemplate.template_id,
                            inputs: {
                                name: { value: 'Function 1' },
                            },
                        },
                    },
                    function_2: {
                        type: 'function',
                        config: {
                            template_id: regularTemplate.template_id,
                            inputs: {
                                name: { value: 'Function 2' },
                            },
                        },
                    },
                    email_1: {
                        type: 'function_email',
                        config: {
                            template_id: 'template-email',
                            inputs: {
                                email: {
                                    value: {
                                        to: {
                                            email: 'recipient@example.com',
                                            name: 'Recipient',
                                        },
                                        from: {
                                            integrationId: 1,
                                            email: 'test@posthog.com',
                                        },
                                        subject: 'Test Email 1',
                                        text: 'Test Text 1',
                                        html: 'Test HTML 1',
                                    },
                                },
                            },
                        },
                    },
                    email_2: {
                        type: 'function_email',
                        config: {
                            template_id: 'template-email',
                            inputs: {
                                email: {
                                    value: {
                                        to: {
                                            email: 'recipient2@example.com',
                                            name: 'Recipient 2',
                                        },
                                        from: {
                                            integrationId: 1,
                                            email: 'test@posthog.com',
                                        },
                                        subject: 'Test Email 2',
                                        text: 'Test Text 2',
                                        html: 'Test HTML 2',
                                    },
                                },
                            },
                        },
                    },
                },
                edges: [
                    { from: 'trigger', to: 'function_1', type: 'continue' },
                    { from: 'function_1', to: 'function_2', type: 'continue' },
                    { from: 'function_2', to: 'email_1', type: 'continue' },
                    { from: 'email_1', to: 'email_2', type: 'continue' },
                    { from: 'email_2', to: 'exit', type: 'continue' },
                ],
            })

            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                    },
                },
            })

            // There are 4 async actions, so we need to execute multiple times until finished
            let result = await executor.execute(invocation)
            while (!result.finished) {
                result = await executor.execute(result.invocation)
            }

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()

            // Verify we have billing metrics for both hog functions and email actions
            const fetchBilling = result.metrics.filter(
                (m) => m.metric_kind === 'fetch' && m.metric_name === 'billable_invocation'
            )
            expect(fetchBilling).toHaveLength(2)
            const emailBilling = result.metrics.filter(
                (m) => m.metric_kind === 'email' && m.metric_name === 'billable_invocation'
            )
            expect(emailBilling).toHaveLength(2)
        })
    })

    function createTestExecutor(redis?: any): HogFlowExecutorService {
        return new HogFlowExecutorService(
            new HogFlowFunctionsService(
                hub.SITE_URL,
                new HogFunctionTemplateManagerService(hub.postgres),
                new HogExecutorService(
                    {
                        hogCostTimingUpperMs: hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                        googleAdwordsDeveloperToken: hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN,
                        fetchRetries: hub.CDP_FETCH_RETRIES,
                        fetchBackoffBaseMs: hub.CDP_FETCH_BACKOFF_BASE_MS,
                        fetchBackoffMaxMs: hub.CDP_FETCH_BACKOFF_MAX_MS,
                    },
                    { teamManager: hub.teamManager, siteUrl: hub.SITE_URL },
                    new HogInputsService(hub.integrationManager, hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL),
                    new EmailService(
                        {
                            sesAccessKeyId: hub.SES_ACCESS_KEY_ID,
                            sesSecretAccessKey: hub.SES_SECRET_ACCESS_KEY,
                            sesRegion: hub.SES_REGION,
                            sesEndpoint: hub.SES_ENDPOINT,
                        },
                        hub.integrationManager,
                        hub.ENCRYPTION_SALT_KEYS,
                        hub.SITE_URL
                    ),
                    new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
                )
            ),
            new RecipientPreferencesService(new RecipientsManagerService(hub.postgres)),
            redis
        )
    }

    describe('ghost run reproduction - March 18-19 incident', () => {
        // This test reproduces the exact production scenario from the March 18-19
        // Cyclotron cross-routing incident. A workflow with trigger -> function -> delay
        // -> function -> exit receives 4 invocations for the same event (1 legitimate
        // + 3 ghost runs from janitor resets). Each invocation has a different ID but
        // carries the same event UUID.

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
                        send_welcome_email: {
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
                        wait_2_days: {
                            type: 'delay',
                            config: { delay_duration: '2d' },
                        },
                        send_followup_email: {
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
                        { from: 'trigger', to: 'send_welcome_email', type: 'continue' },
                        { from: 'send_welcome_email', to: 'wait_2_days', type: 'continue' },
                        { from: 'wait_2_days', to: 'send_followup_email', type: 'continue' },
                        { from: 'send_followup_email', to: 'exit', type: 'continue' },
                    ],
                })
                .build()
        })

        it('without dedup: all 4 invocations execute the function action (the bug)', async () => {
            const executorWithoutDedup = createTestExecutor()

            const sharedEvent = { ...createHogExecutionGlobals().event, uuid: 'user-signup-event-001' }

            // Simulate 4 invocations created by the cross-routing bug
            // Each has a different invocation ID but the same trigger event
            const invocations = Array.from({ length: 4 }, () =>
                createExampleHogFlowInvocation(hogFlow, { event: sharedEvent })
            )

            let fetchCallCount = 0
            for (const invocation of invocations) {
                const beforeFetch = mockFetch.mock.calls.length
                const result = await executorWithoutDedup.execute(invocation)

                // Each invocation reaches the delay step (not finished, scheduled)
                expect(result.invocation.queueScheduledAt).toBeDefined()

                const fetchCalls = mockFetch.mock.calls.length - beforeFetch
                fetchCallCount += fetchCalls
            }

            // BUG: All 4 invocations executed the function, making 4 fetch calls
            // This is the duplicate execution that caused 4x emails in production
            expect(fetchCallCount).toBe(4)
        })

        it('with dedup: only the first invocation executes, ghosts are blocked', async () => {
            const redisStore = new Map<string, { value: string; expiry: number }>()
            const mockRedis = {
                useClient: jest.fn(async (_opts: any, callback: (client: any) => Promise<any>) => {
                    const mockClient = {
                        set: jest.fn((key: string, value: string, _ex: string, ttl: number, _nx: string) => {
                            if (redisStore.has(key)) {
                                return Promise.resolve(null)
                            }
                            redisStore.set(key, { value, expiry: Date.now() + ttl * 1000 })
                            return Promise.resolve('OK')
                        }),
                        get: jest.fn((key: string) => {
                            const entry = redisStore.get(key)
                            return Promise.resolve(entry ? entry.value : null)
                        }),
                    }
                    return callback(mockClient)
                }),
            }

            const executorWithDedup = createTestExecutor(mockRedis as any)

            const sharedEvent = { ...createHogExecutionGlobals().event, uuid: 'user-signup-event-002' }

            const invocations = Array.from({ length: 4 }, () =>
                createExampleHogFlowInvocation(hogFlow, { event: sharedEvent })
            )

            let fetchCallCount = 0
            let blockedCount = 0
            for (const invocation of invocations) {
                const beforeFetch = mockFetch.mock.calls.length
                const result = await executorWithDedup.execute(invocation)

                const fetchCalls = mockFetch.mock.calls.length - beforeFetch
                fetchCallCount += fetchCalls

                const logMessages = result.logs.map((l) => l.message)
                if (logMessages.some((m) => m.includes('duplicate execution detected'))) {
                    blockedCount++
                    // Blocked invocations must not have executed any action
                    expect(logMessages).not.toContainEqual(expect.stringContaining('Executing action'))
                    expect(fetchCalls).toBe(0)
                }
            }

            // FIX: Only 1 invocation executed the function, 3 were blocked
            expect(fetchCallCount).toBe(1)
            expect(blockedCount).toBe(3)
        })
    })

    describe('action deduplication', () => {
        let hogFlow: HogFlow
        let redisStore: Map<string, { value: string; expiry: number }>
        let mockRedis: any

        beforeEach(async () => {
            redisStore = new Map()

            mockRedis = {
                useClient: jest.fn(async (_opts: any, callback: (client: any) => Promise<any>) => {
                    const mockClient = {
                        set: jest.fn((key: string, value: string, _exFlag: string, ttl: number, _nxFlag: string) => {
                            if (redisStore.has(key)) {
                                return Promise.resolve(null) // NX: key already exists
                            }
                            redisStore.set(key, { value, expiry: Date.now() + ttl * 1000 })
                            return Promise.resolve('OK')
                        }),
                        get: jest.fn((key: string) => {
                            const entry = redisStore.get(key)
                            return Promise.resolve(entry ? entry.value : null)
                        }),
                    }
                    return callback(mockClient)
                }),
            }

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
                        { from: 'trigger', to: 'function_id_1', type: 'continue' },
                        { from: 'function_id_1', to: 'exit', type: 'continue' },
                    ],
                })
                .build()

            executor = createTestExecutor(mockRedis)
        })

        it('allows the first invocation to execute', async () => {
            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-123' },
            })

            const result = await executor.execute(invocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()
            expect(mockRedis.useClient).toHaveBeenCalled()
            // Dedup keys set for each action in the workflow (function + exit)
            expect(redisStore.size).toBeGreaterThanOrEqual(1)
        })

        it('blocks a different invocation for the same event and action', async () => {
            // First invocation executes successfully
            const firstInvocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-456' },
            })
            await executor.execute(firstInvocation)
            const fetchCallsAfterFirst = mockFetch.mock.calls.length

            // Second invocation with different ID but same event
            const secondInvocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-456' },
            })

            const result = await executor.execute(secondInvocation)

            expect(result.finished).toBe(true)
            const logMessages = result.logs.map((l) => l.message)
            expect(logMessages).toContainEqual(expect.stringContaining('duplicate execution detected'))
            // The handler must NOT have executed
            expect(logMessages).not.toContainEqual(expect.stringContaining('Executing action'))
            // No fetch calls were made (the hog function template uses fetch)
            expect(mockFetch.mock.calls.length).toBe(fetchCallsAfterFirst)
        })

        it('blocks all 4 ghost runs from the cross-routing incident pattern', async () => {
            const eventUuid = 'event-incident-pattern'
            const invocations = Array.from({ length: 4 }, () =>
                createExampleHogFlowInvocation(hogFlow, {
                    event: { ...createHogExecutionGlobals().event, uuid: eventUuid },
                })
            )

            // First invocation (legitimate) executes successfully
            const firstResult = await executor.execute(invocations[0])
            expect(firstResult.finished).toBe(true)
            expect(firstResult.error).toBeUndefined()

            // Remaining 3 (ghost runs from janitor resets) are all blocked
            for (let i = 1; i < 4; i++) {
                const result = await executor.execute(invocations[i])
                expect(result.finished).toBe(true)
                const logMessages = result.logs.map((l) => l.message)
                expect(logMessages).toContainEqual(expect.stringContaining('duplicate execution detected'))
                expect(logMessages).not.toContainEqual(expect.stringContaining('Executing action'))
            }
        })

        it('first ghost run wins if legitimate invocation already passed before deployment', async () => {
            const eventUuid = 'event-pre-deploy'

            // Simulate: legit invocation already executed before deployment (no Redis key exists)
            // First ghost run arrives after deployment -- it "wins" the key
            const ghostA = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: eventUuid },
            })
            const resultA = await executor.execute(ghostA)
            expect(resultA.finished).toBe(true)
            expect(resultA.error).toBeUndefined() // Ghost A gets through (unavoidable)

            // Subsequent ghosts are blocked
            const ghostB = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: eventUuid },
            })
            const resultB = await executor.execute(ghostB)
            expect(resultB.finished).toBe(true)
            const logMessages = resultB.logs.map((l) => l.message)
            expect(logMessages).toContainEqual(expect.stringContaining('duplicate execution detected'))
        })

        it('allows a legitimate retry (same invocation ID)', async () => {
            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-789' },
            })

            // First execution
            await executor.execute(invocation)

            // Retry with same invocation ID (simulates janitor retry)
            const retryInvocation = { ...invocation }
            retryInvocation.state = {
                ...invocation.state,
                actionStepCount: 0,
                currentAction: undefined,
            }

            const result = await executor.execute(retryInvocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()
            const logMessages = result.logs.map((l) => l.message)
            expect(logMessages).not.toContainEqual(expect.stringContaining('duplicate execution detected'))
        })

        it('allows different events to execute independently', async () => {
            const firstInvocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-aaa' },
            })
            await executor.execute(firstInvocation)

            const secondInvocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-bbb' },
            })
            const result = await executor.execute(secondInvocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()
            const logMessages = result.logs.map((l) => l.message)
            expect(logMessages).not.toContainEqual(expect.stringContaining('duplicate execution detected'))
        })

        it('allows execution when Redis key expires between SET NX and GET', async () => {
            // Simulate: SET NX fails (key exists), but GET returns null (key expired)
            const expiringRedisStore = new Map<string, { value: string; expiry: number }>()
            const expiringMockRedis = {
                useClient: jest.fn(async (_opts: any, callback: (client: any) => Promise<any>) => {
                    const mockClient = {
                        set: jest.fn((key: string, value: string, _ex: string, ttl: number, _nx: string) => {
                            if (expiringRedisStore.has(key)) {
                                return Promise.resolve(null)
                            }
                            expiringRedisStore.set(key, { value, expiry: Date.now() + ttl * 1000 })
                            return Promise.resolve('OK')
                        }),
                        get: jest.fn((_key: string) => {
                            // Always return null to simulate key expiring between SET and GET
                            return Promise.resolve(null)
                        }),
                    }
                    return callback(mockClient)
                }),
            }

            const expiringExecutor = createTestExecutor(expiringMockRedis)

            // First invocation sets the key
            const firstInvocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-expiring' },
            })
            await expiringExecutor.execute(firstInvocation)

            // Second invocation: SET NX fails (key exists), GET returns null (expired)
            // Should fail open and allow execution
            const secondInvocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-expiring' },
            })
            const result = await expiringExecutor.execute(secondInvocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()
            const logMessages = result.logs.map((l) => l.message)
            expect(logMessages).not.toContainEqual(expect.stringContaining('duplicate execution detected'))
        })

        it('also deduplicates non-side-effect actions like delays', async () => {
            const delayFlow: HogFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: {
                                type: 'event',
                                filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                            },
                        },
                        delay_1: {
                            type: 'delay',
                            config: { delay_duration: '1h' },
                        },
                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [
                        { from: 'trigger', to: 'delay_1', type: 'continue' },
                        { from: 'delay_1', to: 'exit', type: 'continue' },
                    ],
                })
                .build()

            // First invocation hits the delay
            const firstInvocation = createExampleHogFlowInvocation(delayFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-delay' },
            })
            await executor.execute(firstInvocation)
            expect(redisStore.size).toBe(1)

            // Ghost run with same event is blocked at the delay step
            const ghostInvocation = createExampleHogFlowInvocation(delayFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-delay' },
            })
            const result = await executor.execute(ghostInvocation)
            expect(result.finished).toBe(true)
            const logMessages = result.logs.map((l) => l.message)
            expect(logMessages).toContainEqual(expect.stringContaining('duplicate execution detected'))
        })

        it('proceeds when Redis is unavailable', async () => {
            mockRedis.useClient.mockRejectedValue(new Error('Redis connection failed'))

            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: { ...createHogExecutionGlobals().event, uuid: 'event-redis-fail' },
            })

            const result = await executor.execute(invocation)

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()
        })
    })
})
