import { KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../src/config/kafka-topics'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { ConfiguredLimiter } from '../../../src/utils/token-bucket'
import { runEventPipeline } from './../../../src/worker/ingestion/event-pipeline/runner'
import { captureIngestionWarning } from './../../../src/worker/ingestion/utils'

jest.mock('../../../src/utils/status')
jest.mock('./../../../src/worker/ingestion/utils')

jest.mock('./../../../src/worker/ingestion/event-pipeline/runner', () => ({
    runEventPipeline: jest.fn().mockResolvedValue('default value'),
}))

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

describe('eachBatchParallelIngestion with overflow reroute', () => {
    let queue: any

    function createBatchWithMultipleEventsWithKeys(events: any[], timestamp?: any): any {
        return events.map((event) => ({
            partition: 0,
            topic: KAFKA_EVENTS_PLUGIN_INGESTION,
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
                    produce: jest.fn(),
                },
                db: 'database',
            },
        }
        jest.mock('./../../../src/worker/ingestion/event-pipeline/runner')
    })

    it('reroutes events with no key to OVERFLOW topic', async () => {
        const batch = [
            {
                partition: 0,
                topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                value: JSON.stringify(captureEndpointEvent),
                timestamp: captureEndpointEvent['timestamp'],
                offset: captureEndpointEvent['offset'],
                key: null,
            },
        ]

        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).not.toHaveBeenCalled()
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            value: JSON.stringify(captureEndpointEvent),
            timestamp: captureEndpointEvent['timestamp'],
            offset: captureEndpointEvent['offset'],
            key: null,
            waitForAck: true,
        })

        // Event is not processed here
        expect(runEventPipeline).not.toHaveBeenCalled()
    })

    it('reroutes excess events to OVERFLOW topic', async () => {
        const now = Date.now()
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent], now)
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1,
            now
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            value: JSON.stringify(captureEndpointEvent),
            timestamp: captureEndpointEvent['timestamp'],
            offset: captureEndpointEvent['offset'],
            key: null,
            waitForAck: true,
        })

        // Event is not processed here
        expect(runEventPipeline).not.toHaveBeenCalled()
    })

    it('does not reroute if not over capacity limit', async () => {
        const now = Date.now()
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent], now)
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => true)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1,
            now
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).not.toHaveBeenCalled()
        // Event is processed
        expect(runEventPipeline).toHaveBeenCalled()
    })
})
