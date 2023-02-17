import { KAFKA_EVENTS_PLUGIN_INGESTION } from '../../../src/config/kafka-topics'
import { eachBatchIngestionFromOverflow } from '../../../src/main/ingestion-queues/analytics-events-ingestion-overflow-consumer'
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

describe('eachBatchIngestionWithOverflow', () => {
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
                WORKER_CONCURRENCY: 1,
                TASKS_PER_WORKER: 10,
                BUFFER_CONVERSION_SECONDS: 60,
                statsd: {
                    timing: jest.fn(),
                    increment: jest.fn(),
                    histogram: jest.fn(),
                    gauge: jest.fn(),
                },
                kafkaProducer: {
                    queueMessage: jest.fn(),
                },
                db: 'database',
            },
            workerMethods: {
                runAsyncHandlersEventPipeline: jest.fn(),
                runEventPipeline: jest.fn(),
                runBufferEventPipeline: jest.fn(),
            },
        }
    })

    it('raises warning when capacity available', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(WarningLimiter, 'consume').mockImplementation(() => true)

        await eachBatchIngestionFromOverflow(batch, queue)

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
    })

    it('does not raise warning capacity limit', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(WarningLimiter, 'consume').mockImplementation(() => false)

        await eachBatchIngestionFromOverflow(batch, queue)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()
    })

    it('runs the rest of the pipeline', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(WarningLimiter, 'consume').mockImplementation(() => false)

        await eachBatchIngestionFromOverflow(batch, queue)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        // This is "the rest of the pipeline"
        expect(queue.workerMethods.runEventPipeline).toHaveBeenCalled()
    })

    it('does not produce the event again', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        jest.spyOn(WarningLimiter, 'consume').mockImplementation(() => false)

        await eachBatchIngestionFromOverflow(batch, queue)

        expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()
    })
})
