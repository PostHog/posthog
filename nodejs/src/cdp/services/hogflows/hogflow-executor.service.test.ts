// sort-imports-ignore
import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder, SimpleHogFlowRepresentation } from '~/cdp/_tests/builders/hogflow.builder'
import { createHogExecutionGlobals, insertHogFunctionTemplate, insertIntegration } from '~/cdp/_tests/fixtures'
import { compileHog } from '~/cdp/templates/compiler'
import { template as posthogCaptureTemplate } from '~/cdp/templates/_destinations/posthog_capture/posthog-capture.template'
import { HogFlow } from '~/cdp/schema/hogflow'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { fetch } from '~/common/utils/request'
import { logger } from '~/common/utils/logger'
import { Hub } from '../../../types'
import { createHub } from '~/common/utils/db/hub'
import { HOG_FILTERS_EXAMPLES } from '../../_tests/examples'
import { createExampleHogFlowInvocation } from '../../_tests/fixtures-hogflows'
import { HogExecutorService } from '../hog-executor.service'
import { HogInputsService } from '../hog-inputs.service'
import { EmailService } from '../messaging/email.service'
import { EmailTrackingCodeSigner } from '../messaging/helpers/tracking-code'
import { RecipientTokensService } from '../messaging/recipient-tokens.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { RecipientsManagerService } from '../managers/recipients-manager.service'
import { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { RecipientPreferencesService } from '../messaging/recipient-preferences.service'
import { HogFlowExecutorService, createHogFlowInvocation } from './hogflow-executor.service'
import { HogFlowFunctionsService } from './hogflow-functions.service'

// Mock before importing fetch
jest.mock('~/common/utils/request', () => {
    const original = jest.requireActual('~/common/utils/request')
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
            new TeamWorkflowsConfigService(hub.postgres),
            hub.ENCRYPTION_SALT_KEYS,
            hub.SITE_URL,
            new EmailTrackingCodeSigner(hub.ENCRYPTION_SALT_KEYS, hub.CDP_EMAIL_TRACKING_URL)
        )
        const recipientTokensService = new RecipientTokensService(hub.ENCRYPTION_SALT_KEYS, hub.SITE_URL)
        const hogExecutor = new HogExecutorService(
            {
                hogCostTimingUpperMs: hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                googleAdwordsDeveloperToken: hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN,
                fetchRetries: hub.CDP_FETCH_RETRIES,
                fetchBackoffBaseMs: hub.CDP_FETCH_BACKOFF_BASE_MS,
                fetchBackoffMaxMs: hub.CDP_FETCH_BACKOFF_MAX_MS,
                selfLoopGuardMode: hub.CDP_SELF_LOOP_GUARD_MODE,
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
                emailAssets: [],
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

            it('surfaces the matcher wake event in the resume log', async () => {
                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        properties: { name: 'Debug User' },
                        timestamp: '2026-01-30T20:20:20.200Z',
                    },
                })
                // Woken by the matcher: the resume log should emit a linkable
                // [Event:uuid|name|timestamp] token, not just echo the trigger event.
                invocation.state.currentAction = {
                    id: 'function_id_1',
                    startedAtTimestamp: DateTime.now().toMillis(),
                    eventMatched: true,
                    eventMatchedEvent: 'subscription created',
                    eventMatchedEventUuid: 'wake-uuid-123',
                    eventMatchedEventTimestamp: '2026-01-30T21:00:00.000Z',
                }

                const result = await executor.execute(invocation)

                expect(result.logs[0].message).toBe(
                    'Resuming workflow execution at [Action:function_id_1] on [Event:uuid|test|2026-01-30T20:20:20.200Z] (woken by [Event:wake-uuid-123|subscription created|2026-01-30T21:00:00.000Z])'
                )
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
                // The property-based conversion is also counted on the exit path
                expect(result2.metrics.map((m) => m.metric_name)).toEqual(['early_exit', 'conversion'])
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
                // The property-based conversion is also counted on the exit path
                expect(result2.metrics.map((m) => m.metric_name)).toEqual(['early_exit', 'conversion'])
                expect(result2.logs.map((log) => log.message)).toMatchInlineSnapshot(`
                    [
                      "Workflow exited early due to exit condition: exit_on_trigger_not_matched_or_conversion ([Person:person_id|John Doe] matches conversion filters)",
                    ]
                `)
            })

            it('counts a property-based conversion without exiting when exit condition is exit_only_at_end', async () => {
                hogFlow.exit_condition = 'exit_only_at_end'
                hogFlow.conversion = {
                    filters: [{ key: '$browser', type: 'person', value: ['Chrome'], operator: 'exact' }],
                    bytecode: ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 32, 'person', 1, 3, 11],
                    window_minutes: null,
                }

                const invocation = createExampleHogFlowInvocation(
                    hogFlow,
                    {
                        event: {
                            ...createHogExecutionGlobals().event,
                            event: '$pageview',
                            properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                        },
                    },
                    { properties: { $browser: 'Chrome' } }
                )

                const result = await executor.execute(invocation)
                // The run completes normally (no early exit) but the conversion is counted exactly once
                expect(result.finished).toBe(true)
                expect(result.metrics.map((m) => m.metric_name)).toEqual([
                    'conversion',
                    'fetch',
                    'billable_invocation',
                    'succeeded',
                    'succeeded',
                ])
                expect(result.metrics.filter((m) => m.metric_name === 'conversion')).toHaveLength(1)
                expect(invocation.state.conversionCounted).toBe(true)
                // The conversion is also surfaced as a billable $workflows_conversion event exactly once.
                const conversionEvents = result.capturedPostHogEvents.filter((e) => e.event === '$workflows_conversion')
                expect(conversionEvents).toHaveLength(1)
                expect(conversionEvents[0]).toMatchObject({
                    distinct_id: 'distinct_id',
                    properties: { $workflow_id: hogFlow.id, $workflow_conversion_type: 'property' },
                })
            })

            it('does not re-count a property-based conversion on a resume that already counted', async () => {
                hogFlow.exit_condition = 'exit_only_at_end'
                hogFlow.conversion = {
                    filters: [{ key: '$browser', type: 'person', value: ['Chrome'], operator: 'exact' }],
                    bytecode: ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 32, 'person', 1, 3, 11],
                    window_minutes: null,
                }

                const invocation = createExampleHogFlowInvocation(
                    hogFlow,
                    {
                        event: {
                            ...createHogExecutionGlobals().event,
                            event: '$pageview',
                            properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                        },
                    },
                    { properties: { $browser: 'Chrome' } }
                )
                // Simulate a prior step in this run having already counted the conversion
                invocation.state.conversionCounted = true

                const result = await executor.execute(invocation)
                expect(result.finished).toBe(true)
                expect(result.metrics.map((m) => m.metric_name)).not.toContain('conversion')
            })

            it('does not count event-based conversions in the executor (counted by the matcher)', async () => {
                hogFlow.exit_condition = 'exit_only_at_end'
                // Event-based conversion goal: no property filters/bytecode, so the executor's
                // property path never matches. The matcher flags the run via conversionMatched.
                hogFlow.conversion = {
                    filters: [],
                    bytecode: [],
                    window_minutes: null,
                    events: [{ filters: { bytecode: ['_H', 1, 29] } }],
                }

                const invocation = createExampleHogFlowInvocation(hogFlow, {
                    event: {
                        ...createHogExecutionGlobals().event,
                        event: '$pageview',
                        properties: { name: 'John Doe', $current_url: 'https://posthog.com' },
                    },
                })
                invocation.state.conversionMatched = true

                const result = await executor.execute(invocation)
                expect(result.finished).toBe(true)
                // No conversion metric from the executor; the flag is consumed, not double-counted
                expect(result.metrics.map((m) => m.metric_name)).not.toContain('conversion')
                expect(invocation.state.conversionMatched).toBe(false)
                expect(invocation.state.conversionCounted).toBeUndefined()
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
                        // Still pending, so the delay parks without advancing currentAction
                        nextActionId: 'delay',
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

    describe('data-warehouse-table trigger', () => {
        // Trigger-source compatibility is decided by the pipeline's eligibilityFn (per consumer),
        // not the executor — coverage for source matching lives in the consumer tests. Here we just
        // assert that when a warehouse-trigger flow with always-true filters is handed to the
        // executor with warehouse-row globals, an invocation is produced.
        it('builds an invocation when filter bytecode evaluates true for warehouse-row globals', async () => {
            const hogFlow = new FixtureHogFlowBuilder()
                .withSimpleWorkflow({
                    trigger: {
                        type: 'data-warehouse-table',
                        table_name: 'postgres.table_1',
                        // Always-true bytecode (return true) like the no-filter data warehouse example
                        filters: { properties: [], bytecode: ['_h', 29] } as any,
                    },
                })
                .build()
            const globals = createHogExecutionGlobals({
                event: {
                    uuid: 'row-uuid-0001',
                    event: '$warehouse_source_row',
                    distinct_id: '',
                    elements_chain: '',
                    timestamp: new Date().toISOString(),
                    url: '',
                    properties: { column1: 'value1', column2: 123, $source_table: 'postgres.table_1' },
                },
            })

            const result = await executor.buildHogFlowInvocations([hogFlow], globals)

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

    describe('group propagation', () => {
        it('carries groups from globals onto the invocation', () => {
            const hogFlow: HogFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'event', filters: {} } },
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [{ from: 'trigger', to: 'exit', type: 'continue' }],
                })
                .build()

            const groups = {
                organization: {
                    id: 'acme-123',
                    type: 'organization',
                    index: 0,
                    url: '',
                    properties: {},
                },
            }
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
                groups,
            }

            const invocation = createHogFlowInvocation(globals, hogFlow, {} as any)

            expect(invocation.groups).toEqual(groups)
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
                            from: {},
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

            // Each execute call returns the metrics for one queue segment, and email
            // actions route through the dedicated email queue — so we accumulate metrics
            // across every segment to assert the total billing over the whole run.
            let result = await executor.execute(invocation)
            const metrics = [...result.metrics]
            while (!result.finished) {
                result = await executor.execute(result.invocation)
                metrics.push(...result.metrics)
            }

            expect(result.finished).toBe(true)
            expect(result.error).toBeUndefined()

            // Verify we have billing metrics for both hog functions and email actions
            const fetchBilling = metrics.filter(
                (m) => m.metric_kind === 'fetch' && m.metric_name === 'billable_invocation'
            )
            expect(fetchBilling).toHaveLength(2)
            const emailBilling = metrics.filter(
                (m) => m.metric_kind === 'email' && m.metric_name === 'billable_invocation'
            )
            expect(emailBilling).toHaveLength(2)
        })
    })

    describe('email queue routing', () => {
        it('should route email actions to the email queue', async () => {
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

            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-email-routing-test',
                name: 'Email Routing Test',
                code: `sendEmail(inputs.email)`,
                inputs_schema: [
                    {
                        type: 'native_email',
                        key: 'email',
                        label: 'Email message',
                        integration: 'email',
                        required: true,
                        default: {
                            to: { email: '', name: '' },
                            from: { email: '', name: '' },
                            subject: '',
                            text: 'Hello!',
                            html: '<div>Hello!</div>',
                        },
                        secret: false,
                        description: '',
                        templating: 'liquid',
                    },
                ],
            })

            const hogFlow = new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withExitCondition('exit_only_at_end')
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: {
                                type: 'event',
                                filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                            },
                        },
                        email_1: {
                            type: 'function_email',
                            config: {
                                template_id: 'template-email-routing-test',
                                inputs: {
                                    email: {
                                        value: {
                                            to: { email: 'recipient@example.com', name: 'Recipient' },
                                            from: { integrationId: 1, email: 'test@posthog.com' },
                                            subject: 'Test Email',
                                            text: 'Test',
                                            html: '<p>Test</p>',
                                        },
                                    },
                                },
                            },
                        },
                    },
                    edges: [
                        { from: 'trigger', to: 'email_1', type: 'continue' },
                        { from: 'email_1', to: 'exit', type: 'continue' },
                    ],
                })
                .build()

            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    event: '$pageview',
                },
            })

            const result = await executor.execute(invocation)

            // Should be routed to email queue, not finished
            expect(result.finished).toBe(false)
            expect(result.invocation.queue).toBe('email')
            expect(result.invocation.queueMetadata?.originQueue).toBeDefined()
            expect(result.invocation.queueParameters).toBeDefined()
            expect(result.invocation.queueParameters?.type).toBe('email')
        })

        it('should complete the full round-trip: hogflow → email queue → email sent → workflow continues', async () => {
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

            await insertHogFunctionTemplate(hub.postgres, {
                id: 'template-email-routing-test',
                name: 'Email Routing Test',
                code: `sendEmail(inputs.email)`,
                inputs_schema: [
                    {
                        type: 'native_email',
                        key: 'email',
                        label: 'Email message',
                        integration: 'email',
                        required: true,
                        default: {
                            to: { email: '', name: '' },
                            from: { email: '', name: '' },
                            subject: '',
                            text: 'Hello!',
                            html: '<div>Hello!</div>',
                        },
                        secret: false,
                        description: '',
                        templating: 'liquid',
                    },
                ],
            })

            const hogFlow = new FixtureHogFlowBuilder()
                .withTeamId(team.id)
                .withExitCondition('exit_only_at_end')
                .withWorkflow({
                    actions: {
                        trigger: {
                            type: 'trigger',
                            config: {
                                type: 'event',
                                filters: HOG_FILTERS_EXAMPLES.no_filters.filters ?? {},
                            },
                        },
                        email_1: {
                            type: 'function_email',
                            config: {
                                template_id: 'template-email-routing-test',
                                inputs: {
                                    email: {
                                        value: {
                                            to: { email: 'recipient@example.com', name: 'Recipient' },
                                            from: { integrationId: 1, email: 'test@posthog.com' },
                                            subject: 'Test Email',
                                            text: 'Test text',
                                            html: '<p>Test html</p>',
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
                        { from: 'trigger', to: 'email_1', type: 'continue' },
                        { from: 'email_1', to: 'exit', type: 'continue' },
                    ],
                })
                .build()

            const invocation = createExampleHogFlowInvocation(hogFlow, {
                event: {
                    ...createHogExecutionGlobals().event,
                    event: '$pageview',
                },
            })

            // Step 1: Hogflow worker executes (queue !== 'email') — should route to email queue
            const hogflowResult = await executor.execute(invocation)
            expect(hogflowResult.finished).toBe(false)
            expect(hogflowResult.invocation.queue).toBe('email')
            expect(hogflowResult.invocation.queueParameters?.type).toBe('email')

            // Step 2: Email worker picks up the job (queue === 'email') — should send inline and continue
            let emailResult = await executor.execute(hogflowResult.invocation)
            while (!emailResult.finished) {
                emailResult = await executor.execute(emailResult.invocation)
            }

            // Workflow should complete
            expect(emailResult.finished).toBe(true)
            expect(emailResult.error).toBeUndefined()

            // Verify email_sent metric was emitted
            const emailSentMetrics = emailResult.metrics.filter((m) => m.metric_name === 'email_sent')
            expect(emailSentMetrics).toHaveLength(1)
        })
    })
})
