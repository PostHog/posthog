import { CdpFunctionCallbackConsumer, CdpProcessedEventsConsumer } from '../../src/cdp/cdp-consumers'
import { HogFunctionInvocationGlobals, HogFunctionType } from '../../src/cdp/types'
import { KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES } from '../../src/config/kafka-topics'
import { Hub, Team } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { waitForExpect } from '../helpers/expectations'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'
import { HOG_EXAMPLES, HOG_FILTERS_EXAMPLES, HOG_INPUTS_EXAMPLES } from './examples'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from './fixtures'
import { createKafkaObserver, TestKafkaObserver } from './helpers/kafka-observer'

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

const mockFetch: jest.Mock = require('../../src/utils/fetch').trackedFetch

describe('CDP E2E', () => {
    let processedEventsConsumer: CdpProcessedEventsConsumer
    let functionProcessor: CdpFunctionCallbackConsumer
    let hub: Hub
    let closeHub: () => Promise<void>
    let team: Team
    let kafkaObserver: TestKafkaObserver

    const insertHogFunction = async (hogFunction: Partial<HogFunctionType>) => {
        const item = await _insertHogFunction(hub.postgres, team.id, hogFunction)
        // Trigger the reload that django would do
        await processedEventsConsumer.hogFunctionManager.reloadAllHogFunctions()
        await functionProcessor.hogFunctionManager.reloadAllHogFunctions()
        return item
    }

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub()
        team = await getFirstTeam(hub)

        kafkaObserver = await createKafkaObserver(hub, [KAFKA_APP_METRICS_2, KAFKA_LOG_ENTRIES])

        processedEventsConsumer = new CdpProcessedEventsConsumer(hub)
        await processedEventsConsumer.start()
        functionProcessor = new CdpFunctionCallbackConsumer(hub)
        await functionProcessor.start()

        mockFetch.mockClear()
    })

    afterEach(async () => {
        try {
            await Promise.all([processedEventsConsumer.stop(), functionProcessor.stop(), kafkaObserver.stop()])
            await closeHub()
        } catch (e) {
            console.error('Error in afterEach:', e)
        }
    })

    afterAll(() => {
        jest.useRealTimers()
    })

    describe.each(['kafka', 'cyclotron'])('e2e fetch call: %s', (mode) => {
        /**
         * Tests here are somewhat expensive so should mostly simulate happy paths and the more e2e scenarios
         */

        let fnFetchNoFilters: HogFunctionType
        let globals: HogFunctionInvocationGlobals

        beforeEach(async () => {
            fnFetchNoFilters = await insertHogFunction({
                ...HOG_EXAMPLES.simple_fetch,
                ...HOG_INPUTS_EXAMPLES.simple_fetch,
                ...HOG_FILTERS_EXAMPLES.no_filters,
            })

            globals = createHogExecutionGlobals({
                project: {
                    id: team.id,
                } as any,
                event: {
                    uuid: 'b3a1fe86-b10c-43cc-acaf-d208977608d0',
                    name: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com',
                        $lib_version: '1.0.0',
                    },
                    timestamp: '2024-09-03T09:00:00Z',
                } as any,
            })

            if (mode === 'cyclotron') {
                hub.CDP_CYCLOTRON_ENABLED_TEAMS = '*'
                hub.CYCLOTRON_DATABASE_URL = 'postgres://localhost:5432/test_cyclotron'
            }
        })

        it('should invoke a function via kafka transportation until completed', async () => {
            // NOTE: We can skip kafka as the entry point
            const invocations = await processedEventsConsumer.processBatch([globals])
            expect(invocations).toHaveLength(1)

            await waitForExpect(() => {
                expect(kafkaObserver.messages).toHaveLength(6)
            })

            expect(mockFetch).toHaveBeenCalledTimes(1)

            expect(mockFetch.mock.calls[0]).toMatchInlineSnapshot(`
                Array [
                  "https://example.com/posthog-webhook",
                  Object {
                    "body": "{\\"event\\":{\\"uuid\\":\\"b3a1fe86-b10c-43cc-acaf-d208977608d0\\",\\"name\\":\\"$pageview\\",\\"distinct_id\\":\\"distinct_id\\",\\"url\\":\\"http://localhost:8000/events/1\\",\\"properties\\":{\\"$current_url\\":\\"https://posthog.com\\",\\"$lib_version\\":\\"1.0.0\\"},\\"timestamp\\":\\"2024-09-03T09:00:00Z\\"},\\"groups\\":{},\\"nested\\":{\\"foo\\":\\"http://localhost:8000/events/1\\"},\\"person\\":{\\"uuid\\":\\"uuid\\",\\"name\\":\\"test\\",\\"url\\":\\"http://localhost:8000/persons/1\\",\\"properties\\":{\\"email\\":\\"test@posthog.com\\"}},\\"event_url\\":\\"http://localhost:8000/events/1-test\\"}",
                    "headers": Object {
                      "version": "v=1.0.0",
                    },
                    "method": "POST",
                    "timeout": 10000,
                  },
                ]
            `)

            expect(kafkaObserver.messages).toMatchObject([
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
    })
})
