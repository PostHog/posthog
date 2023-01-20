import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
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
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({ APP_METRICS_FLUSH_FREQUENCY_MS: 100 })
        appMetrics = new AppMetrics(hub)

        jest.spyOn(hub.organizationManager, 'hasAvailableFeature').mockResolvedValue(true)
        jest.spyOn(hub.kafkaProducer, 'queueMessage').mockReturnValue(Promise.resolve())
    })

    afterEach(async () => {
        jest.useRealTimers()
        if (appMetrics.timer) {
            clearTimeout(appMetrics.timer)
        }
        await closeHub()
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

        it('creates timer to flush if no timer before', async () => {
            jest.spyOn(appMetrics, 'flush')
            jest.useFakeTimers()

            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)

            const timer = appMetrics.timer
            expect(timer).not.toBeNull()

            jest.advanceTimersByTime(120)

            expect(appMetrics.timer).toBeNull()
            expect(appMetrics.flush).toHaveBeenCalled()
        })

        it('does not create a timer on subsequent requests', async () => {
            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)
            const originalTimer = appMetrics.timer
            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)

            expect(originalTimer).not.toBeNull()
            expect(appMetrics.timer).toEqual(originalTimer)
        })

        it('does nothing if feature is not available', async () => {
            jest.mocked(hub.organizationManager.hasAvailableFeature).mockResolvedValue(false)

            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)
            expect(appMetrics.queuedData).toEqual({})
        })

        it('does not query `hasAvailableFeature` if not needed', async () => {
            hub.APP_METRICS_GATHERED_FOR_ALL = true

            await appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp)

            expect(appMetrics.queuedData).not.toEqual({})
            expect(hub.organizationManager.hasAvailableFeature).not.toHaveBeenCalled()
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
            const spy = jest.spyOn(hub.kafkaProducer, 'queueMessage')

            await appMetrics.queueMetric({ ...metric, jobId: '000-000', successes: 1 }, timestamp)
            await appMetrics.flush()

            expect(spy.mock.calls).toMatchSnapshot()
        })

        it('does nothing if nothing queued', async () => {
            await appMetrics.flush()

            expect(hub.kafkaProducer.queueMessage).not.toHaveBeenCalled()
        })
    })

    describe('reading writes from clickhouse', () => {
        async function fetchRowsFromClickhouse() {
            return (await hub.db.clickhouseQuery(`SELECT * FROM app_metrics FINAL`)).data
        }

        beforeEach(async () => {
            await resetTestDatabaseClickhouse()
            jest.mocked(hub.kafkaProducer.queueMessage).mockRestore()
        })

        it('can read its own writes', async () => {
            await Promise.all([
                appMetrics.queueMetric({ ...metric, successes: 1 }, timestamp),
                appMetrics.queueMetric({ ...metric, successes: 2, successesOnRetry: 4 }, timestamp),
                appMetrics.queueMetric({ ...metric, failures: 1 }, timestamp),
            ])

            await appMetrics.flush()
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

            await appMetrics.queueError(
                { ...metric, failures: 1 },
                { error: new Error('foobar'), eventCount: 1 },
                timestamp
            ),
                await appMetrics.flush()
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
