// eslint-disable-next-line simple-import-sort/imports
import { getParsedQueuedMessages, mockProducer } from '../../helpers/mocks/producer.mock'

import { HogWatcherState } from '../../../src/cdp/services/hog-watcher.service'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../../../src/cdp/types'
import { Hub, Team } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../../helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from '../examples'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from '../fixtures'
import { CdpProcessedEventsConsumer } from '../../../src/cdp/consumers/cdp-processed-events.consumer'
import { CdpInternalEventsConsumer } from '../../../src/cdp/consumers/cdp-internal-event.consumer'

const mockConsumer = {
    on: jest.fn(),
    commitSync: jest.fn(),
    commit: jest.fn(),
    queryWatermarkOffsets: jest.fn(),
    committed: jest.fn(),
    assignments: jest.fn(),
    isConnected: jest.fn(() => true),
    getMetadata: jest.fn(),
}

jest.mock('../../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: mockConsumer,
            })
        ),
    }
})

jest.mock('../../../src/utils/fetch', () => {
    return {
        trackedFetch: jest.fn(() =>
            Promise.resolve({
                status: 200,
                text: () => Promise.resolve(JSON.stringify({ success: true })),
                json: () => Promise.resolve({ success: true }),
            })
        ),
    }
})

const mockFetch: jest.Mock = require('../../../src/utils/fetch').trackedFetch

jest.setTimeout(1000)

type DecodedKafkaMessage = {
    topic: string
    key?: any
    value: Record<string, unknown>
}

const decodeAllKafkaMessages = (): DecodedKafkaMessage[] => {
    const queuedMessages = getParsedQueuedMessages()

    const result: DecodedKafkaMessage[] = []

    for (const topicMessage of queuedMessages) {
        for (const message of topicMessage.messages) {
            result.push({
                topic: topicMessage.topic,
                key: message.key,
                value: message.value ?? {},
            })
        }
    }

    return result
}

// Add mock for CyclotronManager
const mockBulkCreateJobs = jest.fn()
jest.mock('@posthog/cyclotron', () => ({
    CyclotronManager: jest.fn().mockImplementation(() => ({
        connect: jest.fn(),
        bulkCreateJobs: mockBulkCreateJobs,
    })),
}))

/**
 * NOTE: The internal and normal events consumers are very similar so we can test them together
 */
describe.each([
    [CdpProcessedEventsConsumer.name, CdpProcessedEventsConsumer, 'destination' as const],
    [CdpInternalEventsConsumer.name, CdpInternalEventsConsumer, 'internal_destination' as const],
])('%s', (_name, Consumer, hogType) => {
    let processor: CdpProcessedEventsConsumer | CdpInternalEventsConsumer
    let hub: Hub
    let team: Team

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, {
            ...hogFunction,
            type: hogType,
        })
        // Trigger the reload that django would do
        await processor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()

        team = await getFirstTeam(hub)

        processor = new Consumer(hub)
        await processor.start()

        mockFetch.mockClear()
        mockBulkCreateJobs.mockClear()
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await processor.stop()
        await closeHub(hub)
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe('general event processing', () => {
        describe('common processing', () => {
            let fnFetchNoFilters: HogFunctionType
            let fnPrinterPageviewFilters: HogFunctionType
            let globals: HogFunctionInvocationGlobals

            beforeEach(async () => {
                fnFetchNoFilters = await insertHogFunction({
                    ...HOG_EXAMPLES.simple_fetch,
                    ...HOG_INPUTS_EXAMPLES.simple_fetch,
                    ...HOG_FILTERS_EXAMPLES.no_filters,
                })

                fnPrinterPageviewFilters = await insertHogFunction({
                    ...HOG_EXAMPLES.input_printer,
                    ...HOG_INPUTS_EXAMPLES.secret_inputs,
                    ...HOG_FILTERS_EXAMPLES.pageview_or_autocapture_filter,
                })

                globals = createHogExecutionGlobals({
                    project: {
                        id: team.id,
                    } as any,
                    event: {
                        uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $lib_version: '1.0.0',
                        },
                    } as any,
                })
            })

            const matchInvocation = (hogFunction: HogFunctionType, globals: HogFunctionInvocationGlobals) => {
                return {
                    hogFunction: {
                        id: hogFunction.id,
                    },
                    globals: {
                        event: globals.event,
                    },
                }
            }

            it('should process events', async () => {
                const invocations = await processor.processBatch([globals])

                expect(invocations).toHaveLength(2)
                expect(invocations).toMatchObject([
                    matchInvocation(fnFetchNoFilters, globals),
                    matchInvocation(fnPrinterPageviewFilters, globals),
                ])

                // Verify Cyclotron jobs
                expect(mockBulkCreateJobs).toHaveBeenCalledWith(
                    expect.arrayContaining([
                        expect.objectContaining({
                            teamId: team.id,
                            functionId: fnFetchNoFilters.id,
                            queueName: 'hog',
                            priority: 1,
                            vmState: expect.objectContaining({
                                hogFunctionId: fnFetchNoFilters.id,
                                teamId: team.id,
                                queue: 'hog',
                                globals: expect.any(Object),
                            }),
                        }),
                        expect.objectContaining({
                            teamId: team.id,
                            functionId: fnPrinterPageviewFilters.id,
                            queueName: 'hog',
                            priority: 1,
                            vmState: expect.objectContaining({
                                hogFunctionId: fnPrinterPageviewFilters.id,
                                teamId: team.id,
                                queue: 'hog',
                                globals: expect.any(Object),
                            }),
                        }),
                    ])
                )
            })

            it("should filter out functions that don't match the filter", async () => {
                globals.event.properties.$current_url = 'https://nomatch.com'

                const invocations = await processor.processBatch([globals])

                expect(invocations).toHaveLength(1)
                expect(invocations).toMatchObject([matchInvocation(fnFetchNoFilters, globals)])

                // Verify only one Cyclotron job is created (for fnFetchNoFilters)
                expect(mockBulkCreateJobs).toHaveBeenCalledWith(
                    expect.arrayContaining([
                        expect.objectContaining({
                            teamId: team.id,
                            functionId: fnFetchNoFilters.id,
                            queueName: 'hog',
                            priority: 1,
                            vmState: expect.objectContaining({
                                hogFunctionId: fnFetchNoFilters.id,
                                teamId: team.id,
                                queue: 'hog',
                                globals: expect.any(Object),
                            }),
                        }),
                    ])
                )

                // Still verify the metric for the filtered function
                expect(decodeAllKafkaMessages()).toMatchObject([
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnPrinterPageviewFilters.id,
                            count: 1,
                            metric_kind: 'other',
                            metric_name: 'filtered',
                            team_id: 2,
                            timestamp: expect.any(String),
                        },
                    },
                ])
            })

            it.each([
                [HogWatcherState.disabledForPeriod, 'disabled_temporarily'],
                [HogWatcherState.disabledIndefinitely, 'disabled_permanently'],
            ])('should filter out functions that are disabled', async (state, metric_name) => {
                await processor.hogWatcher.forceStateChange(fnFetchNoFilters.id, state)
                await processor.hogWatcher.forceStateChange(fnPrinterPageviewFilters.id, state)

                const invocations = await processor.processBatch([globals])

                expect(invocations).toHaveLength(0)
                expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)

                expect(decodeAllKafkaMessages()).toMatchObject([
                    {
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnFetchNoFilters.id,
                            count: 1,
                            metric_kind: 'failure',
                            metric_name: metric_name,
                            team_id: 2,
                        },
                    },
                    {
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: fnPrinterPageviewFilters.id,
                            count: 1,
                            metric_kind: 'failure',
                            metric_name: metric_name,
                            team_id: 2,
                        },
                    },
                ])
            })
        })

        describe('filtering errors', () => {
            let globals: HogFunctionInvocationGlobals

            beforeEach(() => {
                globals = createHogExecutionGlobals({
                    project: {
                        id: team.id,
                    } as any,
                    event: {
                        uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                        event: '$pageview',
                        properties: {
                            $current_url: 'https://posthog.com',
                            $lib_version: '1.0.0',
                        },
                    } as any,
                })
            })

            it('should filter out functions that error while filtering', async () => {
                const erroringFunction = await insertHogFunction({
                    ...HOG_EXAMPLES.input_printer,
                    ...HOG_INPUTS_EXAMPLES.secret_inputs,
                    ...HOG_FILTERS_EXAMPLES.broken_filters,
                })
                await processor.processBatch([globals])
                expect(decodeAllKafkaMessages()).toMatchObject([
                    {
                        key: expect.any(String),
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            app_source_id: erroringFunction.id,
                            count: 1,
                            metric_kind: 'other',
                            metric_name: 'filtering_failed',
                            team_id: 2,
                            timestamp: expect.any(String),
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message:
                                'Error filtering event b3a1fe86-b10c-43cc-acaf-d208977608d0: Invalid HogQL bytecode, stack is empty, can not pop',
                        },
                    },
                ])
            })
        })
    })
})
