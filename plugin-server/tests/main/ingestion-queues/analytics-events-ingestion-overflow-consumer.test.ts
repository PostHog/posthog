import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../../src/config/kafka-topics'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { eachBatchLegacyIngestion } from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion-kafkajs'
import { WarningLimiter } from '../../../src/utils/token-bucket'
import { captureIngestionWarning } from './../../../src/worker/ingestion/utils'

jest.mock('../../../src/utils/status')
jest.mock('./../../../src/worker/ingestion/utils')

const captureEndpointEvent = {
    uuid: 'uuid1',
    distinct_id: 'id',
    ip: null,
    site_url: '',
    data: JSON.stringify({
        event: 'event',
        properties: {},
    }),
    team_id: 1,
    now: null,
    sent_at: null,
}

describe('eachBatchParallelIngestion with overflow consume', () => {
    let queue: any

    function createBatchWithMultipleEventsWithKeys(events: any[], timestamp?: any): any {
        return events.map((event) => ({
            value: JSON.stringify(event),
            timestamp,
            offset: event.offset,
            key: event.team_id + ':' + event.distinct_id,
        }))
    }

    beforeEach(() => {
        queue = {
            bufferSleep: jest.fn(),
            pluginsServer: {
                INGESTION_CONCURRENCY: 4,
                statsd: {
                    timing: jest.fn(),
                    increment: jest.fn(),
                    histogram: jest.fn(),
                    gauge: jest.fn(),
                },
                kafkaProducer: {
                    queueMessage: jest.fn(),
                },
                teamManager: {
                    getTeamForEvent: jest.fn(),
                },
                db: 'database',
            },
            workerMethods: {
                runEventPipeline: jest.fn(() => Promise.resolve({})),
            },
        }
    })

    it('raises ingestion warning when consuming from overflow', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(WarningLimiter, 'consume').mockImplementation(() => true)

        queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Consume)

        expect(queue.pluginsServer.teamManager.getTeamForEvent).toHaveBeenCalledTimes(1)
        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).toHaveBeenCalledWith(
            queue.pluginsServer.db,
            captureEndpointEvent['team_id'],
            'ingestion_capacity_overflow',
            {
                overflowDistinctId: captureEndpointEvent['distinct_id'],
            }
        )

        // Event is processed
        expect(queue.workerMethods.runEventPipeline).toHaveBeenCalled()
    })

    it('does not raise ingestion warning when under threshold', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(WarningLimiter, 'consume').mockImplementation(() => false)

        queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Consume)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()

        // Event is processed
        expect(queue.workerMethods.runEventPipeline).toHaveBeenCalled()
    })
})

describe('eachBatchLegacyIngestion with overflow consume', () => {
    let queue: any

    function createBatchWithMultipleEventsWithKeys(events: any[], timestamp?: any): any {
        return {
            batch: {
                partition: 0,
                topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                messages: events.map((event) => ({
                    value: JSON.stringify(event),
                    timestamp,
                    offset: event.offset,
                    key: event.team_id + ':' + event.distinct_id,
                })),
            },
            resolveOffset: jest.fn(),
            heartbeat: jest.fn(),
            commitOffsetsIfNecessary: jest.fn(),
            isRunning: jest.fn(() => true),
            isStale: jest.fn(() => false),
        }
    }

    beforeEach(() => {
        queue = {
            bufferSleep: jest.fn(),
            pluginsServer: {
                INGESTION_CONCURRENCY: 4,
                statsd: {
                    timing: jest.fn(),
                    increment: jest.fn(),
                    histogram: jest.fn(),
                    gauge: jest.fn(),
                },
                kafkaProducer: {
                    queueMessage: jest.fn(),
                },
                teamManager: {
                    getTeamForEvent: jest.fn(),
                },
                db: 'database',
            },
            workerMethods: {
                runEventPipeline: jest.fn(() => Promise.resolve({})),
            },
        }
    })

    it('raises ingestion warning when consuming from overflow', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(WarningLimiter, 'consume').mockImplementation(() => true)

        queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
        await eachBatchLegacyIngestion(batch, queue, IngestionOverflowMode.Consume)

        expect(queue.pluginsServer.teamManager.getTeamForEvent).toHaveBeenCalledTimes(1)
        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).toHaveBeenCalledWith(
            queue.pluginsServer.db,
            captureEndpointEvent['team_id'],
            'ingestion_capacity_overflow',
            {
                overflowDistinctId: captureEndpointEvent['distinct_id'],
            }
        )

        // Event is processed
        expect(queue.workerMethods.runEventPipeline).toHaveBeenCalled()
    })

    it('does not raise ingestion warning when under threshold', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(WarningLimiter, 'consume').mockImplementation(() => false)

        queue.pluginsServer.teamManager.getTeamForEvent.mockResolvedValueOnce({ id: 1 })
        await eachBatchLegacyIngestion(batch, queue, IngestionOverflowMode.Consume)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()

        // Event is processed
        expect(queue.workerMethods.runEventPipeline).toHaveBeenCalled()
    })
})
