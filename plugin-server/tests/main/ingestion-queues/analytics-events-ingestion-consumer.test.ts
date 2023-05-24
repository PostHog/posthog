import { KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../src/config/kafka-topics'
import { eachBatchIngestionWithOverflow } from '../../../src/main/ingestion-queues/analytics-events-ingestion-consumer'
import {
    eachBatchParallelIngestion,
    IngestionOverflowMode,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { ConfiguredLimiter } from '../../../src/utils/token-bucket'
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
                INGESTION_CONCURRENCY: 4,
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
            },
        }
    })

    it('re produces event back to OVERFLOW topic', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        await eachBatchIngestionWithOverflow(batch, queue)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.queueMessage).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            messages: [
                {
                    value: JSON.stringify(captureEndpointEvent),
                    timestamp: captureEndpointEvent['timestamp'],
                    offset: captureEndpointEvent['offset'],
                    key: null,
                },
            ],
        })
    })

    it('does not reproduce if not over capacity limit', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => true)

        await eachBatchIngestionWithOverflow(batch, queue)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()
    })

    it('does not run the rest of the pipeline if overflowing', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        await eachBatchIngestionWithOverflow(batch, queue)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(queue.pluginsServer.kafkaProducer.queueMessage).toHaveBeenCalledWith({
            topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
            messages: [
                {
                    value: JSON.stringify(captureEndpointEvent),
                    timestamp: captureEndpointEvent['timestamp'],
                    offset: captureEndpointEvent['offset'],
                    key: null,
                },
            ],
        })
        // This is "the rest of the pipeline"
        expect(queue.workerMethods.runEventPipeline).not.toHaveBeenCalled()
    })
})

describe('eachBatchParallelIngestion with overflow reroute', () => {
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
                db: 'database',
            },
            workerMethods: {
                runAsyncHandlersEventPipeline: jest.fn(),
                runEventPipeline: jest.fn(),
            },
        }
    })

    it('reroutes events with no key to OVERFLOW topic', async () => {
        const batch = {
            batch: {
                partition: 0,
                topic: KAFKA_EVENTS_PLUGIN_INGESTION,
                messages: [
                    {
                        value: JSON.stringify(captureEndpointEvent),
                        timestamp: captureEndpointEvent['timestamp'],
                        offset: captureEndpointEvent['offset'],
                        key: null,
                    },
                ],
            },
            resolveOffset: jest.fn(),
            heartbeat: jest.fn(),
            commitOffsetsIfNecessary: jest.fn(),
            isRunning: jest.fn(() => true),
            isStale: jest.fn(() => false),
        }
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).not.toHaveBeenCalled()
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.queueMessage).toHaveBeenCalledWith(
            {
                topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
                messages: [
                    {
                        value: JSON.stringify(captureEndpointEvent),
                        timestamp: captureEndpointEvent['timestamp'],
                        offset: captureEndpointEvent['offset'],
                        key: null,
                    },
                ],
            },
            true
        )

        // Event is not processed here
        expect(queue.workerMethods.runEventPipeline).not.toHaveBeenCalled()
    })

    it('reroutes excess events to OVERFLOW topic', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

        expect(consume).toHaveBeenCalledWith(
            captureEndpointEvent['team_id'] + ':' + captureEndpointEvent['distinct_id'],
            1
        )
        expect(captureIngestionWarning).not.toHaveBeenCalled()
        expect(queue.pluginsServer.kafkaProducer.queueMessage).toHaveBeenCalledWith(
            {
                topic: KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW,
                messages: [
                    {
                        value: JSON.stringify(captureEndpointEvent),
                        timestamp: captureEndpointEvent['timestamp'],
                        offset: captureEndpointEvent['offset'],
                        key: null,
                    },
                ],
            },
            true
        )

        // Event is not processed here
        expect(queue.workerMethods.runEventPipeline).not.toHaveBeenCalled()
    })

    it('does not reroute if not over capacity limit', async () => {
        const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
        const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => true)

        await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Reroute)

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
