import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
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

describe('Hogflow Executor', () => {
    let executor: HogFlowExecutorService
    let hub: Hub

    beforeEach(async () => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        await resetTestDatabase()
        hub = await createHub()
        const hogExecutor = new HogExecutorService(hub)
        const hogFunctionTemplateManager = new HogFunctionTemplateManagerService(hub)

        const exampleHog = `
            print(f'Hello, {inputs.name}!')
            fetch('https://posthog.com')`

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

        it('can execute a hogflow', async () => {
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
                        actionStepCount: 0,
                        currentAction: {
                            id: 'exit',
                            startedAtTimestamp: expect.any(Number),
                        },
                        event: {
                            distinct_id: 'distinct_id',
                            elements_chain: '',
                            event: 'test',
                            properties: {
                                $lib_version: '1.2.3',
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
                        message: `Workflow completed`,
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
    })
})
