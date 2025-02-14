// eslint-disable-next-line simple-import-sort/imports
import { getProducedKafkaMessages, getProducedKafkaMessagesForTopic } from '../helpers/mocks/producer.mock'

import { CdpCyclotronWorker, CdpCyclotronWorkerFetch } from '../../src/cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpProcessedEventsConsumer } from '../../src/cdp/consumers/cdp-processed-events.consumer'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../../src/cdp/types'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { waitForExpect } from '../helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from './fixtures'

jest.mock('../../src/utils/fetch', () => {
    return {
        trackedFetch: jest.fn(() =>
            Promise.resolve({
                status: 200,
                text: () => Promise.resolve(JSON.stringify({ success: true })),
                headers: new Headers({ 'Content-Type': 'application/json' }),
                json: () => Promise.resolve({ success: true }),
            })
        ),
    }
})

const mockFetch: jest.Mock = require('../../src/utils/fetch').trackedFetch

describe('CDP Consumer loop', () => {
    jest.setTimeout(10000)

    describe('e2e fetch call', () => {
        let processedEventsConsumer: CdpProcessedEventsConsumer
        let cyclotronWorker: CdpCyclotronWorker | undefined
        let cyclotronFetchWorker: CdpCyclotronWorkerFetch | undefined

        let hub: Hub
        let team: Team
        let fnFetchNoFilters: HogFunctionType
        let globals: HogFunctionInvocationGlobals

        const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
            const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
            return item
        }

        beforeEach(async () => {
            await resetTestDatabase()
            hub = await createHub()
            team = await getFirstTeam(hub)

            fnFetchNoFilters = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            hub.CYCLOTRON_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron'

            processedEventsConsumer = new CdpProcessedEventsConsumer(hub)
            await processedEventsConsumer.start()

            cyclotronWorker = new CdpCyclotronWorker(hub)
            await cyclotronWorker.start()
            cyclotronFetchWorker = new CdpCyclotronWorkerFetch(hub)
            await cyclotronFetchWorker.start()

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
                    timestamp: '2024-09-03T09:00:00Z',
                } as any,
            })

            mockFetch.mockClear()
            // Clear any existing messages at the start of each test
            getProducedKafkaMessages().length = 0
        })

        afterEach(async () => {
            const stoppers = [
                processedEventsConsumer?.stop().then(() => console.log('Stopped processedEventsConsumer')),
                cyclotronWorker?.stop().then(() => console.log('Stopped cyclotronWorker')),
                cyclotronFetchWorker?.stop().then(() => console.log('Stopped cyclotronFetchWorker')),
            ]

            await Promise.all(stoppers)

            await closeHub(hub)
        })

        afterAll(() => {
            jest.useRealTimers()
        })

        /**
         * Tests here are somewhat expensive so should mostly simulate happy paths and the more e2e scenarios
         */

        it('should invoke a function in the worker loop until completed', async () => {
            const invocations = await processedEventsConsumer.processBatch([globals])
            expect(invocations).toHaveLength(1)

            await waitForExpect(() => {
                const logMessages = getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
                const metricsMessages = getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)

                // Verify exact counts
                expect(logMessages).toHaveLength(3)
                expect(metricsMessages).toHaveLength(2)

                // Verify metrics messages
                expect(metricsMessages).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            value: expect.objectContaining({
                                app_source: 'hog_function',
                                app_source_id: fnFetchNoFilters.id.toString(),
                                metric_kind: 'other',
                                metric_name: 'fetch',
                            }),
                        }),
                        expect.objectContaining({
                            value: expect.objectContaining({
                                app_source: 'hog_function',
                                app_source_id: fnFetchNoFilters.id.toString(),
                                metric_kind: 'success',
                                metric_name: 'succeeded',
                            }),
                        }),
                    ])
                )

                // Verify log messages
                expect(logMessages).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            value: expect.objectContaining({
                                level: 'debug',
                                message: expect.stringContaining('Suspending function due to async function call'),
                            }),
                        }),
                        expect.objectContaining({
                            value: expect.objectContaining({
                                level: 'info',
                                message: expect.stringContaining('Fetch response:'),
                            }),
                        }),
                        expect.objectContaining({
                            value: expect.objectContaining({
                                level: 'debug',
                                message: expect.stringContaining('Function completed in'),
                            }),
                        }),
                    ])
                )
            }, 5000)

            expect(mockFetch).toHaveBeenCalledTimes(1)

            expect(mockFetch.mock.calls[0]).toMatchInlineSnapshot(`
                [
                  "https://example.com/posthog-webhook",
                  {
                    "body": "{"event":{"uuid":"b3a1fe86-b10c-43cc-acaf-d208977608d0","event":"$pageview","elements_chain":"","distinct_id":"distinct_id","url":"http://localhost:8000/events/1","properties":{"$current_url":"https://posthog.com","$lib_version":"1.0.0"},"timestamp":"2024-09-03T09:00:00Z"},"groups":{},"nested":{"foo":"http://localhost:8000/events/1"},"person":{"id":"uuid","name":"test","url":"http://localhost:8000/persons/1","properties":{"email":"test@posthog.com","first_name":"Pumpkin"}},"event_url":"http://localhost:8000/events/1-test"}",
                    "headers": {
                      "version": "v=1.0.0",
                    },
                    "method": "POST",
                    "timeout": 10000,
                  },
                ]
            `)
        })
    })
})
