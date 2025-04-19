// eslint-disable-next-line simple-import-sort/imports
import { getProducedKafkaMessages, getProducedKafkaMessagesForTopic } from '~/tests/helpers/mocks/producer.mock'

import { CdpCyclotronWorker } from '../../src/cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpCyclotronWorkerFetch } from '../../src/cdp/consumers/cdp-cyclotron-worker-fetch.consumer'
import { CdpProcessedEventsConsumer } from '../../src/cdp/consumers/cdp-processed-events.consumer'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../../src/cdp/types'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { waitForExpect } from '~/tests/helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from './_tests/fixtures'
import { FetchError } from 'node-fetch'
import { forSnapshot } from '~/tests/helpers/snapshots'

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

            hub.CDP_FETCH_RETRIES = 2
            hub.CDP_FETCH_BACKOFF_BASE_MS = 100 // fast backoff

            fnFetchNoFilters = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            hub.CYCLOTRON_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/rust_test_database'

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
                expect(getProducedKafkaMessages()).toHaveLength(7)
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

            const logMessages = getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
            const metricsMessages = getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)

            expect(metricsMessages).toMatchObject([
                {
                    topic: 'clickhouse_app_metrics2_test',
                    value: {
                        app_source: 'hog_function',
                        app_source_id: fnFetchNoFilters.id.toString(),
                        count: 1,
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        team_id: 2,
                    },
                },
                {
                    topic: 'clickhouse_app_metrics2_test',
                    value: {
                        app_source: 'hog_function',
                        app_source_id: fnFetchNoFilters.id.toString(),
                        count: 1,
                        metric_kind: 'success',
                        metric_name: 'succeeded',
                        team_id: 2,
                    },
                },
            ])

            expect(logMessages).toMatchObject([
                {
                    topic: 'log_entries_test',
                    value: {
                        level: 'debug',
                        log_source: 'hog_function',
                        log_source_id: fnFetchNoFilters.id.toString(),
                        message: 'Executing function',
                        team_id: 2,
                    },
                },
                {
                    topic: 'log_entries_test',
                    value: {
                        level: 'debug',
                        log_source: 'hog_function',
                        log_source_id: fnFetchNoFilters.id.toString(),
                        message: expect.stringContaining(
                            "Suspending function due to async function call 'fetch'. Payload:"
                        ),
                        team_id: 2,
                    },
                },
                {
                    topic: 'log_entries_test',
                    value: {
                        level: 'debug',
                        log_source: 'hog_function',
                        log_source_id: fnFetchNoFilters.id.toString(),
                        message: 'Resuming function',
                        team_id: 2,
                    },
                },
                {
                    topic: 'log_entries_test',
                    value: {
                        level: 'info',
                        log_source: 'hog_function',
                        log_source_id: fnFetchNoFilters.id.toString(),
                        message: `Fetch response:, {"status":200,"body":{"success":true}}`,
                        team_id: 2,
                    },
                },
                {
                    topic: 'log_entries_test',
                    value: {
                        level: 'debug',
                        log_source: 'hog_function',
                        log_source_id: fnFetchNoFilters.id.toString(),
                        message: expect.stringContaining('Function completed in'),
                        team_id: 2,
                    },
                },
            ])
        })

        it('should handle fetch failures with retries', async () => {
            mockFetch.mockRejectedValue(new FetchError('Test error', 'request-timeout'))

            const invocations = await processedEventsConsumer.processBatch([globals])

            expect(invocations).toHaveLength(1)

            await waitForExpect(() => {
                expect(getProducedKafkaMessages().length).toBeGreaterThan(10)
            }, 5000)

            const logMessages = getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)

            // Ignore the last message as it is non-deterministic
            expect(forSnapshot(logMessages.map((m) => m.value.message).slice(0, -1))).toMatchInlineSnapshot(`
                [
                  "Executing function",
                  "Suspending function due to async function call 'fetch'. Payload: 2031 bytes. Event: <REPLACED-UUID-0>",
                  "Fetch failed after 2 attempts",
                  "Fetch failure of kind timeout with status (none) and message FetchError: Test error",
                  "Fetch failure of kind timeout with status (none) and message FetchError: Test error",
                  "Resuming function",
                  "Fetch response:, {"status":503,"body":{"event":{"uuid":"<REPLACED-UUID-0>","event":"$pageview","elements_chain":"","distinct_id":"distinct_id","url":"http://localhost:8000/events/1","properties":{"$current_url":"https://posthog.com","$lib_version":"1.0.0"},"timestamp":"2024-09-03T09:00:00Z"},"groups":{},"nested":{"foo":"http://localhost:8000/events/1"},"person":{"id":"uuid","name":"test","url":"http://localhost:8000/persons/1","properties":{"email":"test@posthog.com","first_name":"Pumpkin"}},"event_url":"http://localhost:8000/events/1-test"}}",
                ]
            `)
        })
    })
})
