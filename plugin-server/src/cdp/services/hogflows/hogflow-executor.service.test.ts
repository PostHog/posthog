import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HogFlow } from '~/schema/hogflow'

import { Hub } from '../../../types'
import { createHub } from '../../../utils/db/hub'
import { HOG_FILTERS_EXAMPLES } from '../../_tests/examples'
import { createExampleHogFlowInvocation } from '../../_tests/fixtures-hogflows'
import { HogFlowExecutorService } from './hogflow-executor.service'

describe('Hogflow Executor', () => {
    jest.setTimeout(1000)
    let executor: HogFlowExecutorService
    let hub: Hub

    beforeEach(async () => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())
        hub = await createHub()
        executor = new HogFlowExecutorService(hub)
    })

    describe('general event processing', () => {
        let hogFlow: HogFlow

        beforeEach(() => {
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
                        exit: {
                            type: 'exit',
                            config: {},
                        },
                    },
                    edges: [
                        {
                            from: 'trigger',
                            to: 'exit',
                            type: 'continue',
                        },
                    ],
                })
                .build()
        })

        it('can execute a hogflow', async () => {
            const invocation = createExampleHogFlowInvocation(hogFlow)

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
