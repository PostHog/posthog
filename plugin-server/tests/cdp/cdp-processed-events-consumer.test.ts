import { CdpProcessedEventsConsumer } from '../../src/cdp/cdp-consumers'
import { HogWatcherState } from '../../src/cdp/hog-watcher'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../../src/cdp/types'
import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from './fixtures'

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

jest.mock('../../src/kafka/batch-consumer', () => {
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

jest.mock('../../src/utils/fetch', () => {
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

jest.mock('../../src/utils/db/kafka-producer-wrapper', () => {
    const mockKafkaProducer = {
        producer: {
            connect: jest.fn(),
        },
        disconnect: jest.fn(),
        produce: jest.fn(() => Promise.resolve()),
    }
    return {
        KafkaProducerWrapper: jest.fn(() => mockKafkaProducer),
    }
})

const mockFetch: jest.Mock = require('../../src/utils/fetch').trackedFetch

const mockProducer = require('../../src/utils/db/kafka-producer-wrapper').KafkaProducerWrapper()

jest.setTimeout(1000)

const decodeKafkaMessage = (message: any): any => {
    return {
        ...message,
        value: JSON.parse(message.value.toString()),
    }
}

const decodeAllKafkaMessages = (): any[] => {
    return mockProducer.produce.mock.calls.map((x) => decodeKafkaMessage(x[0]))
}

describe('CDP Processed Events Consumer', () => {
    let processor: CdpProcessedEventsConsumer
    let hub: Hub
    let team: Team

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        await processor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)

        processor = new CdpProcessedEventsConsumer(hub)
        await processor.start()

        mockFetch.mockClear()
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

                expect(mockProducer.produce).toHaveBeenCalledTimes(11)
                expect(decodeAllKafkaMessages()).toMatchObject([
                    {
                        topic: 'log_entries_test',
                        value: {
                            message: 'Executing function',
                            log_source_id: fnFetchNoFilters.id,
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message: "Suspending function due to async function call 'fetch'. Payload: 1956 bytes",
                            log_source_id: fnFetchNoFilters.id,
                        },
                    },
                    {
                        topic: 'clickhouse_app_metrics2_test',
                        value: {
                            app_source: 'hog_function',
                            team_id: 2,
                            app_source_id: fnPrinterPageviewFilters.id,
                            metric_kind: 'success',
                            metric_name: 'succeeded',
                            count: 1,
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message: 'Executing function',
                            log_source_id: fnPrinterPageviewFilters.id,
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message: 'test',
                            log_source_id: fnPrinterPageviewFilters.id,
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message: '{"nested":{"foo":"***REDACTED***","bool":false,"null":null}}',
                            log_source_id: fnPrinterPageviewFilters.id,
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message: '{"foo":"***REDACTED***","bool":false,"null":null}',
                            log_source_id: fnPrinterPageviewFilters.id,
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message: 'substring: ***REDACTED***',
                            log_source_id: fnPrinterPageviewFilters.id,
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message:
                                '{"input_1":"test","secret_input_2":{"foo":"***REDACTED***","bool":false,"null":null},"secret_input_3":"***REDACTED***"}',
                            log_source_id: fnPrinterPageviewFilters.id,
                        },
                    },
                    {
                        topic: 'log_entries_test',
                        value: {
                            message: expect.stringContaining('Function completed'),
                            log_source_id: fnPrinterPageviewFilters.id,
                        },
                    },
                    {
                        topic: 'cdp_function_callbacks_test',
                        value: {
                            state: expect.any(String),
                        },
                        key: expect.stringContaining(fnFetchNoFilters.id.toString()),
                        waitForAck: true,
                    },
                ])
            })

            it("should filter out functions that don't match the filter", async () => {
                globals.event.properties.$current_url = 'https://nomatch.com'

                const invocations = await processor.processBatch([globals])

                expect(invocations).toHaveLength(1)
                expect(invocations).toMatchObject([matchInvocation(fnFetchNoFilters, globals)])
                expect(mockProducer.produce).toHaveBeenCalledTimes(4)

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
                    {
                        topic: 'log_entries_test',
                    },
                    {
                        topic: 'log_entries_test',
                    },
                    {
                        topic: 'cdp_function_callbacks_test',
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
                expect(mockProducer.produce).toHaveBeenCalledTimes(2)

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
    })
})
