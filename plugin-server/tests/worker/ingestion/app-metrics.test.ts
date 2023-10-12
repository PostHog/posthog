import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { KafkaProducerWrapper } from '../../../src/utils/db/kafka-producer-wrapper'
import { UUIDT } from '../../../src/utils/utils'
import { AppMetricIdentifier, AppMetrics } from '../../../src/worker/ingestion/app-metrics'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../helpers/clickhouse'

jest.mock('../../../src/utils/status')

const metric: AppMetricIdentifier = {
    teamId: 2,
    pluginConfigId: 2,
    category: 'processEvent',
}

const timestamp = 1_000_000

const uuid1 = new UUIDT().toString()
const uuid2 = new UUIDT().toString()

describe('AppMetrics()', () => {
    let appMetrics: AppMetrics
    let kafkaProducer: KafkaProducerWrapper

    beforeEach(() => {
        kafkaProducer = {
            producer: jest.fn(),
            waitForAck: jest.fn(),
            produce: jest.fn(),
            queueMessage: jest.fn(),
            flush: jest.fn(),
            disconnect: jest.fn(),
        } as unknown as KafkaProducerWrapper

        appMetrics = new AppMetrics(kafkaProducer, 100, 5)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('queueMetric()', () => {
        it('creates a new data entry with relevant counters', async () => {
            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)

            expect(Object.values(appMetrics.queuedData)).toEqual([
                {
                    successes: 1,
                    successesOnRetry: 0,
                    failures: 0,
                    lastTimestamp: timestamp,
                    queuedAt: timestamp,
                    metric: {
                        teamId: 2,
                        pluginConfigId: 2,
                        category: 'processEvent',
                    },
                },
            ])
        })

        it('increments relevant counters', async () => {
            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)
            await appMetrics.queueMetric(
                {
                    ...metric,
                    category: 'onEvent',
                    failures: 1,
                },
                timestamp + 1000
            )
            await appMetrics.queueMetric(
                {
                    ...metric,
                    successesOnRetry: 2,
                },
                timestamp + 2000
            )

            expect(Object.values(appMetrics.queuedData)).toEqual([
                {
                    successes: 1,
                    successesOnRetry: 2,
                    failures: 0,
                    lastTimestamp: timestamp + 2000,
                    queuedAt: timestamp,
                    metric: {
                        teamId: 2,
                        pluginConfigId: 2,
                        category: 'processEvent',
                    },
                },
                {
                    successes: 0,
                    successesOnRetry: 0,
                    failures: 1,
                    lastTimestamp: timestamp + 1000,
                    queuedAt: timestamp + 1000,
                    metric: {
                        teamId: 2,
                        pluginConfigId: 2,
                        category: 'onEvent',
                    },
                },
            ])
        })

        it('stores separate entries for errors', async () => {
            await appMetrics.queueMetric(
                {
                    ...metric,
                    failures: 1,
                    errorUuid: uuid1,
                    errorType: 'SomeError',
                    errorDetails: '{}',
                },
                timestamp
            )
            await appMetrics.queueMetric(
                {
                    ...metric,
                    failures: 1,
                    errorUuid: uuid2,
                    errorType: 'SomeError',
                    errorDetails: '{}',
                },
                timestamp + 1000
            )

            expect(Object.values(appMetrics.queuedData)).toEqual([
                {
                    successes: 0,
                    successesOnRetry: 0,
                    failures: 1,

                    errorUuid: uuid1,
                    errorType: 'SomeError',
                    errorDetails: '{}',

                    lastTimestamp: timestamp,
                    queuedAt: timestamp,
                    metric: {
                        teamId: 2,
                        pluginConfigId: 2,
                        category: 'processEvent',
                    },
                },
                {
                    successes: 0,
                    successesOnRetry: 0,
                    failures: 1,

                    errorUuid: uuid2,
                    errorType: 'SomeError',
                    errorDetails: '{}',

                    lastTimestamp: timestamp + 1000,
                    queuedAt: timestamp + 1000,
                    metric: {
                        teamId: 2,
                        pluginConfigId: 2,
                        category: 'processEvent',
                    },
                },
            ])
        })

        it('flushes when time is up', async () => {
            Date.now = jest.fn(() => 1600000000)
            await appMetrics.flush()

            jest.spyOn(appMetrics, 'flush')
            Date.now = jest.fn(() => 1600000120)

            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)

            expect(appMetrics.flush).toHaveBeenCalledTimes(1)
            // doesn't flush again on the next call, i.e. flust metrics were reset
            Date.now = jest.fn(() => 1600000130)
            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)
            expect(appMetrics.flush).toHaveBeenCalledTimes(1)
        })

        it('flushes when max queue size is hit', async () => {
            jest.spyOn(appMetrics, 'flush')
            // parallel could trigger multiple flushes and make the test flaky
            for (let i = 0; i < 7; i++) {
                await appMetrics.queueMetric({ ...metric, successes: 1, teamId: i }, timestamp)
            }
            expect(appMetrics.flush).toHaveBeenCalledTimes(1)
            // we only count different keys, so this should not trigger a flush
            for (let i = 0; i < 7; i++) {
                await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)
            }
            expect(appMetrics.flush).toHaveBeenCalledTimes(1)
        })
    })

    describe('queueError()', () => {
        const failureMetric = { ...metric, failures: 1 }

        beforeEach(() => {
            jest.spyOn(appMetrics, 'queueMetric')
        })

        it('queues Error objects', async () => {
            await appMetrics.queueError(failureMetric, { error: new Error('foobar'), eventCount: 2 }, timestamp)

            const call = jest.mocked(appMetrics.queueMetric).mock.calls[0]

            expect(call).toEqual([
                {
                    ...failureMetric,
                    errorUuid: expect.any(String),
                    errorType: 'Error',
                    errorDetails: expect.any(String),
                },
                timestamp,
            ])
            expect(JSON.parse(call[0].errorDetails)).toEqual({
                error: {
                    name: 'Error',
                    message: 'foobar',
                    stack: expect.stringContaining('Error: foobar\n'),
                },
                eventCount: 2,
            })
        })

        it('queues String objects', async () => {
            await appMetrics.queueError(failureMetric, { error: 'StringError', eventCount: 2 }, timestamp)

            const call = jest.mocked(appMetrics.queueMetric).mock.calls[0]
            expect(call).toEqual([
                {
                    ...failureMetric,
                    errorUuid: expect.any(String),
                    errorType: 'StringError',
                    errorDetails: expect.any(String),
                },
                timestamp,
            ])
            expect(JSON.parse(call[0].errorDetails)).toEqual({
                error: {
                    name: 'StringError',
                },
                eventCount: 2,
            })
        })

        it('handles errors gracefully', async () => {
            // @ts-expect-error This will cause an error downstream
            await appMetrics.queueError(failureMetric, { error: undefined, eventCount: 2 }, timestamp)

            expect(appMetrics.queueMetric).toHaveBeenCalledWith(failureMetric, timestamp)
        })
    })

    describe('flush()', () => {
        it('flushes queued messages', async () => {
            const spy = jest.spyOn(kafkaProducer, 'queueMessage')

            await appMetrics.queueMetric({ ...metric, jobId: '000-000', successes: 1 }, timestamp)
            await appMetrics.flush()

            expect(spy.mock.calls).toMatchSnapshot()
        })

        it('does nothing if nothing queued', async () => {
            await appMetrics.flush()

            expect(kafkaProducer.queueMessage).not.toHaveBeenCalled()
        })
    })

    describe('reading writes from clickhouse', () => {
        let hub: Hub
        let closeHub: () => Promise<void>

        beforeEach(async () => {
            ;[hub, closeHub] = await createHub({
                APP_METRICS_FLUSH_FREQUENCY_MS: 100,
                APP_METRICS_FLUSH_MAX_QUEUE_SIZE: 5,
            })
            // doesn't flush again on the next call, i.e. flust metrics were reset
            jest.spyOn(hub.kafkaProducer, 'queueMessage').mockReturnValue(Promise.resolve())
        })
        afterEach(async () => {
            await closeHub()
        })
        async function fetchRowsFromClickhouse() {
            return (await hub.db.clickhouseQuery(`SELECT * FROM app_metrics FINAL`)).data
        }

        beforeEach(async () => {
            await resetTestDatabaseClickhouse()
            jest.mocked(hub.kafkaProducer.queueMessage).mockRestore()
        })

        it('can read its own writes', async () => {
            await Promise.all([
                hub.appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp),
                hub.appMetrics.queueMetric({ ...metric, successes: 2, successesOnRetry: 4 }, timestamp),
                hub.appMetrics.queueMetric({ ...metric, failures: 1 }, timestamp),
            ])

            await hub.appMetrics.flush()
            await hub.kafkaProducer.flush()

            const rows = await delayUntilEventIngested(fetchRowsFromClickhouse)
            expect(rows.length).toEqual(1)
            expect(rows[0]).toEqual(
                expect.objectContaining({
                    timestamp: '1970-01-01 00:16:40.000000',
                    team_id: metric.teamId,
                    plugin_config_id: metric.pluginConfigId,
                    category: metric.category,
                    job_id: '',
                    successes: 3,
                    successes_on_retry: 4,
                    failures: 1,
                    error_uuid: '00000000-0000-0000-0000-000000000000',
                    error_type: '',
                    error_details: '',
                })
            )
        })

        it('can read errors', async () => {
            jest.spyOn

            await hub.appMetrics.queueError(
                { ...metric, failures: 1 },
                { error: new Error('foobar'), eventCount: 1 },
                timestamp
            ),
                await hub.appMetrics.flush()
            await hub.kafkaProducer.flush()

            const rows = await delayUntilEventIngested(fetchRowsFromClickhouse)

            expect(rows.length).toEqual(1)
            expect(rows[0]).toEqual(
                expect.objectContaining({
                    timestamp: '1970-01-01 00:16:40.000000',
                    team_id: metric.teamId,
                    plugin_config_id: metric.pluginConfigId,
                    category: metric.category,
                    job_id: '',
                    successes: 0,
                    successes_on_retry: 0,
                    failures: 1,
                    error_type: 'Error',
                })
            )
            expect(rows[0].error_uuid).not.toEqual('00000000-0000-0000-0000-000000000000')
            expect(JSON.parse(rows[0].error_details)).toEqual({
                error: {
                    name: 'Error',
                    message: 'foobar',
                    stack: expect.stringContaining('Error: foobar\n'),
                },
                eventCount: 1,
            })
        })
    })
})
