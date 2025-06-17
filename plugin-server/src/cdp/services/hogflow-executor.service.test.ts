import { HogFlow } from '~/schema/hogflow'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { HOG_FILTERS_EXAMPLES } from '../_tests/examples'
import { createExampleHogFlowInvocation, createHogFlow, createHogFlowAction } from '../_tests/fixtures-hogflows'
import { HogFlowExecutorService } from './hogflow-executor.service'

describe('Hogflow Executor', () => {
    jest.setTimeout(1000)
    let executor: HogFlowExecutorService
    let hub: Hub

    beforeEach(async () => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2024-06-07T12:00:00.000Z').getTime())
        hub = await createHub()
        executor = new HogFlowExecutorService(hub)
    })

    describe('general event processing', () => {
        let hogFlow: HogFlow

        beforeEach(() => {
            hogFlow = createHogFlow({
                actions: [
                    createHogFlowAction({
                        id: '1',
                        type: 'trigger',
                        config: {
                            filters: HOG_FILTERS_EXAMPLES.no_filters.filters,
                        },
                    }),
                ],
            })
        })

        it('can execute an invocation', async () => {
            const invocation = createExampleHogFlowInvocation(hogFlow)

            const result = await executor.execute(invocation)
            expect(result).toEqual({
                capturedPostHogEvents: [],
                invocation: {
                    state: {
                        actionStepCount: 0,
                        currentAction: {
                            id: '1',
                            startedAtTimestamp: expect.any(Number),
                        },
                        event: {
                            distinct_id: 'distinct_id',
                            elements_chain: '',
                            event: 'test',
                            properties: {
                                $lib_version: '1.2.3',
                            },
                            timestamp: '2024-06-07T12:00:00.000Z',
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
                error: 'Action type trigger not supported',
                finished: true,
                logs: expect.any(Array),
                metrics: [],
            })
        })
    })
})
