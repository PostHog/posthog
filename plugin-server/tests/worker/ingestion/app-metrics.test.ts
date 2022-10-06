import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { AppMetric, AppMetrics } from '../../../src/worker/ingestion/app-metrics'

jest.mock('../../../src/utils/status')

const metric: AppMetric = {
    teamId: 2,
    pluginConfigId: 2,
    category: 'processEvent',

    successes: 1,
}

const timestamp = 1_000_000

describe('AppMetrics()', () => {
    let appMetrics: AppMetrics
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({ APP_METRICS_MAX_QUEUE_SIZE: 2, APP_METRICS_FLUSH_FREQUENCY_MS: 100 })
        appMetrics = new AppMetrics(hub)

        jest.spyOn(hub.organizationManager, 'hasAvailableFeature').mockResolvedValue(true)
        jest.spyOn(hub.db.kafkaProducer, 'queueMessage').mockReturnValue(Promise.resolve())
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
            await appMetrics.queueMetric(metric, timestamp)

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
            await appMetrics.queueMetric(metric, timestamp)
            await appMetrics.queueMetric(
                {
                    ...metric,
                    category: 'onEvent',
                    successes: 0,
                    failures: 1,
                },
                timestamp + 1000
            )
            await appMetrics.queueMetric(
                {
                    ...metric,
                    successes: 0,
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

        it('automatically flushes queue if full', async () => {
            jest.spyOn(appMetrics, 'flush')

            await appMetrics.queueMetric({ ...metric, teamId: 1 })
            await appMetrics.queueMetric({ ...metric, teamId: 1 })
            await appMetrics.queueMetric({ ...metric, teamId: 2 })
            expect(appMetrics.flush).not.toHaveBeenCalled()

            await appMetrics.queueMetric({ ...metric, teamId: 3 })
            expect(appMetrics.flush).toHaveBeenCalled()
        })

        it('creates timer to flush if no timer before', async () => {
            jest.spyOn(appMetrics, 'flush')
            jest.useFakeTimers()

            await appMetrics.queueMetric(metric, timestamp)

            const timer = appMetrics.timer
            expect(timer).not.toBeNull()

            jest.advanceTimersByTime(120)

            expect(appMetrics.timer).toBeNull()
            expect(appMetrics.flush).toHaveBeenCalled()
        })

        it('does not create a timer on subsequent requests', async () => {
            await appMetrics.queueMetric(metric, timestamp)
            const originalTimer = appMetrics.timer
            await appMetrics.queueMetric(metric, timestamp)

            expect(originalTimer).not.toBeNull()
            expect(appMetrics.timer).toEqual(originalTimer)
        })

        it('does nothing if feature is not available', async () => {
            jest.mocked(hub.organizationManager.hasAvailableFeature).mockResolvedValue(false)

            await appMetrics.queueMetric(metric, timestamp)
            expect(appMetrics.queuedData).toEqual({})
        })
    })

    describe('flush()', () => {
        it('flushes queued messages', async () => {
            const spy = jest.spyOn(hub.db.kafkaProducer, 'queueMessage')

            await appMetrics.queueMetric({ ...metric, jobId: '000-000' }, timestamp)
            await appMetrics.flush()

            expect(spy.mock.calls).toMatchSnapshot()
        })

        it('does nothing if nothing queued', async () => {
            await appMetrics.flush()

            expect(hub.db.kafkaProducer.queueMessage).not.toHaveBeenCalled()
        })
    })
})
