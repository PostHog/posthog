import { buildStringMatcher } from '../../../src/config/config'
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

const captureEndpointEvent1 = {
    uuid: 'uuid1',
    distinct_id: 'id',
    ip: null,
    site_url: '',
    data: JSON.stringify({
        event: 'event',
        properties: {},
    }),
    token: 'mytoken',
    now: null,
    sent_at: null,
}

const captureEndpointEvent2 = {
    uuid: 'uuid2',
    distinct_id: 'id',
    ip: null,
    site_url: '',
    data: JSON.stringify({
        event: 'event',
        properties: {},
    }),
    token: 'othertoken',
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
                value: JSON.stringify(captureEndpointEvent1),
                timestamp: captureEndpointEvent1['timestamp'],
                offset: captureEndpointEvent1['offset'],
                key: null,
                token: 'ok',
            },
        ]

        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        const tokenBlockList = buildStringMatcher('another_token,more_token', false)
        await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).not.toHaveBeenCalled()
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            value: JSON.stringify(captureEndpointEvent1),
            timestamp: captureEndpointEvent1['timestamp'],
            offset: captureEndpointEvent1['offset'],
            key: null,
            waitForAck: true,
        })

        // Event is not processed here
        expect(runEventPipeline).not.toHaveBeenCalled()
    })

    it('reroutes excess events to OVERFLOW topic', async () => {
        const now = Date.now()
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent1], now)
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        const tokenBlockList = buildStringMatcher('another_token,more_token', false)
        await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent1['token'] + ':' + captureEndpointEvent1['distinct_id'],
            1,
            now
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            value: JSON.stringify(captureEndpointEvent1),
            timestamp: captureEndpointEvent1['timestamp'],
            offset: captureEndpointEvent1['offset'],
            key: null,
            waitForAck: true,
        })

        // Event is not processed here
        expect(runEventPipeline).not.toHaveBeenCalled()
    })

    it('does not reroute if not over capacity limit', async () => {
        const now = Date.now()
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent1, captureEndpointEvent2], now)
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => true)

        const tokenBlockList = buildStringMatcher('another_token,more_token', false)
        await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent1['token'] + ':' + captureEndpointEvent1['distinct_id'],
            1,
            now
        )
        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent2['token'] + ':' + captureEndpointEvent2['distinct_id'],
            1,
            now
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).not.toHaveBeenCalled()
        // Event is processed
        expect(runEventPipeline).toHaveBeenCalledTimes(2)
    })

    it('does drop events from blocked tokens', async () => {
        const now = Date.now()
        const batch = createBatchWithMultipleEventsWithKeys(
            [captureEndpointEvent1, captureEndpointEvent2, captureEndpointEvent1],
            now
        )
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => true)

        const tokenBlockList = buildStringMatcher('mytoken,another_token', false)
        await eachBatchParallelIngestion(tokenBlockList, batch, queue, IngestionOverflowMode.Reroute)

        // Event captureEndpointEvent1 is dropped , captureEndpointEvent2 goes though
        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent2['token'] + ':' + captureEndpointEvent2['distinct_id'],
            1,
            now
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.produce).not.toHaveBeenCalled()
        expect(runEventPipeline).toHaveBeenCalledTimes(1)
    })
})
