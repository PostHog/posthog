// eslint-disable-next-line simple-import-sort/imports
import { MockKafkaProducerWrapper } from '~/tests/helpers/mocks/producer.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { CdpCyclotronWorker } from '../../src/cdp/consumers/cdp-cyclotron-worker.consumer'
import { CdpCyclotronWorkerFetch } from '../../src/cdp/consumers/cdp-cyclotron-worker-fetch.consumer'
import { CdpEventsConsumer } from './consumers/cdp-events.consumer'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../../src/cdp/types'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { Hub, Team } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { waitForExpect } from '~/tests/helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './_tests/examples'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from './_tests/fixtures'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { KafkaProducerObserver } from '~/tests/helpers/mocks/producer.spy'
import { resetKafka } from '~/tests/helpers/kafka'
import { logger } from '../utils/logger'

const ActualKafkaProducerWrapper = jest.requireActual('../../src/kafka/producer').KafkaProducerWrapper

describe.each(['postgres' as const, 'kafka' as const, 'hybrid' as const])('CDP Consumer loop: %s', (mode) => {
    jest.setTimeout(10000)

    describe('e2e fetch call', () => {
        let eventsConsumer: CdpEventsConsumer
        let cyclotronWorker: CdpCyclotronWorker | undefined
        let cyclotronFetchWorker: CdpCyclotronWorkerFetch | undefined

        let hub: Hub
        let team: Team
        let fnFetchNoFilters: HogFunctionType
        let globals: HogFunctionInvocationGlobals
        let mockProducerObserver: KafkaProducerObserver

        const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
            const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
            return item
        }

        beforeEach(async () => {
            // We still want to mock all created producers but we wan't to use the real implementation, not the mocked one
            MockKafkaProducerWrapper.create = jest.fn((...args) => {
                return ActualKafkaProducerWrapper.create(...args)
            })

            await resetKafka()

            await resetTestDatabase()
            hub = await createHub()
            team = await getFirstTeam(hub)
            mockProducerObserver = new KafkaProducerObserver(hub.kafkaProducer)
            mockProducerObserver.resetKafkaProducer()

            hub.CDP_FETCH_RETRIES = 2
            hub.CDP_FETCH_BACKOFF_BASE_MS = 100 // fast backoff
            hub.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA = true
            hub.CYCLOTRON_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron'
            hub.CDP_CYCLOTRON_JOB_QUEUE_PRODUCER_MAPPING =
                mode === 'hybrid' ? '*:kafka,fetch:postgres' : mode === 'postgres' ? '*:postgres' : '*:kafka'

            fnFetchNoFilters = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            eventsConsumer = new CdpEventsConsumer({
                ...hub,
                CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: mode === 'hybrid' ? 'kafka' : mode,
            })
            await eventsConsumer.start()

            cyclotronWorker = new CdpCyclotronWorker({
                ...hub,
                CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: mode === 'hybrid' ? 'kafka' : mode, // hybrid mode we do hog on kafka
            })
            await cyclotronWorker.start()
            cyclotronFetchWorker = new CdpCyclotronWorkerFetch({
                ...hub,
                CDP_CYCLOTRON_JOB_QUEUE_CONSUMER_MODE: mode === 'hybrid' ? 'postgres' : mode, // hybrid mode we do fetch on postgres
            })
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

            mockFetch.mockResolvedValue({
                status: 200,
                json: () => Promise.resolve({ success: true }),
                text: () => Promise.resolve(JSON.stringify({ success: true })),
                headers: { 'Content-Type': 'application/json' },
            })

            expect(mockProducerObserver.getProducedKafkaMessages()).toHaveLength(0)
        })

        afterEach(async () => {
            const stoppers = [
                eventsConsumer?.stop().then(() => console.log('Stopped eventsConsumer')),
                cyclotronWorker?.stop().then(() => console.log('Stopped cyclotronWorker')),
                cyclotronFetchWorker?.stop().then(() => console.log('Stopped cyclotronFetchWorker')),
            ]

            await Promise.all(stoppers)
            await closeHub(hub)
            mockProducerObserver.resetKafkaProducer()
        })

        afterAll(() => {
            jest.useRealTimers()
        })

        /**
         * Tests here are somewhat expensive so should mostly simulate happy paths and the more e2e scenarios
         */

        it('should invoke a function in the worker loop until completed', async () => {
            const { invocations } = await eventsConsumer.processBatch([globals])
            expect(invocations).toHaveLength(1)

            try {
                await waitForExpect(() => {
                    expect(mockProducerObserver.getProducedKafkaMessagesForTopic('log_entries_test')).toHaveLength(5)
                }, 5000)
            } catch (e) {
                logger.warn('[TESTS] Failed to wait for log messages', {
                    messages: mockProducerObserver.getProducedKafkaMessages(),
                })
                throw e
            }

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
                    "timeoutMs": 10000,
                  },
                ]
            `)

            const logMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)
            const metricsMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_APP_METRICS_2)

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
            mockFetch.mockImplementation(() => {
                return Promise.resolve({
                    status: 500,
                    headers: {},
                    json: () => Promise.resolve({ error: 'Server error' }),
                    text: () => Promise.resolve(JSON.stringify({ error: 'Server error' })),
                })
            })

            const { invocations } = await eventsConsumer.processBatch([globals])

            expect(invocations).toHaveLength(1)

            await waitForExpect(() => {
                expect(mockProducerObserver.getProducedKafkaMessages().length).toBeGreaterThan(10)
            }, 5000).catch((e) => {
                logger.warn('[TESTS] Failed to wait for log messages', {
                    messages: mockProducerObserver.getProducedKafkaMessages(),
                })
                throw e
            })

            const logMessages = mockProducerObserver.getProducedKafkaMessagesForTopic(KAFKA_LOG_ENTRIES)

            // Ignore the last message as it is non-deterministic
            expect(
                forSnapshot(
                    logMessages
                        .slice(0, -1)
                        .map((m) => m.value.message)
                        // Sorted compare as the messages can get logged in different orders
                        .sort()
                )
            ).toEqual([
                'Executing function',
                'Fetch failed after 2 attempts',
                'Fetch failure of kind failurestatus with status 500 and message Received failure status: 500',
                'Fetch failure of kind failurestatus with status 500 and message Received failure status: 500',
                'Fetch response:, {"status":500,"body":{"error":"Server error"}}',
                'Resuming function',
                "Suspending function due to async function call 'fetch'. Payload: 2031 bytes. Event: <REPLACED-UUID-0>",
            ])
        })
    })
})
