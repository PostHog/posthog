import { KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../src/config/kafka-topics'
import { eachBatch } from '../../../src/main/ingestion-queues/batch-processing/each-batch'
import { eachBatchAsyncHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-async-handlers'
import { eachBatchIngestion } from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { ClickHouseTimestamp, ISOTimestamp, PostIngestionEvent, RawClickHouseEvent } from '../../../src/types'
import { ConfiguredLimiter } from '../../../src/utils/token-bucket'
import { groupIntoBatches } from '../../../src/utils/utils'
import { captureIngestionWarning } from './../../../src/worker/ingestion/utils'

jest.mock('../../../src/utils/status')
jest.mock('./../../../src/worker/ingestion/utils')

const event: PostIngestionEvent = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00.000Z' as ISOTimestamp,
    event: '$pageview',
    properties: {},
    elementsList: [],
}

const clickhouseEvent: RawClickHouseEvent = {
    event: '$pageview',
    properties: JSON.stringify({
        $ip: '127.0.0.1',
    }),
    uuid: 'uuid1',
    elements_chain: '',
    timestamp: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
    team_id: 2,
    distinct_id: 'my_id',
    created_at: '2020-02-23 02:15:00.00' as ClickHouseTimestamp,
}

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

describe('eachBatchX', () => {
    let queue: any

    function createBatchWithMultipleEvents(events: any[], timestamp?: any): any {
        return {
            batch: {
                partition: 0,
                messages: events.map((event) => ({
                    value: JSON.stringify(event),
                    timestamp,
                    offset: event.offset,
                })),
            },
            resolveOffset: jest.fn(),
            heartbeat: jest.fn(),
            commitOffsetsIfNecessary: jest.fn(),
            isRunning: jest.fn(() => true),
            isStale: jest.fn(() => false),
        }
    }

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

    function createBatch(event: any, timestamp?: any): any {
        return createBatchWithMultipleEvents([event], timestamp)
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
            },
            workerMethods: {
                runAsyncHandlersEventPipeline: jest.fn(),
                runEventPipeline: jest.fn(),
                runBufferEventPipeline: jest.fn(),
            },
        }
    })

    describe('eachBatch', () => {
        it('calls eachMessage with the correct arguments', async () => {
            const eachMessage = jest.fn()
            const batch = createBatch(event)
            await eachBatch(batch, queue, eachMessage, groupIntoBatches, 'key')

            expect(eachMessage).toHaveBeenCalledWith({ value: JSON.stringify(event) }, queue)
        })

        it('tracks metrics based on the key', async () => {
            const eachMessage = jest.fn()
            await eachBatch(createBatch(event), queue, eachMessage, groupIntoBatches, 'my_key')

            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_my_key',
                expect.any(Date)
            )
        })
    })

    describe('eachBatchAsyncHandlers', () => {
        it('calls runAsyncHandlersEventPipeline', async () => {
            await eachBatchAsyncHandlers(createBatch(clickhouseEvent), queue)

            expect(queue.workerMethods.runAsyncHandlersEventPipeline).toHaveBeenCalledWith({
                ...event,
                properties: {
                    $ip: '127.0.0.1',
                },
            })
            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_async_handlers',
                expect.any(Date)
            )
        })
    })

    describe('eachBatchIngestion', () => {
        it('calls runLightweightCaptureEndpointEventPipeline', async () => {
            const batch = createBatch(captureEndpointEvent)
            await eachBatchIngestion(batch, queue)

            expect(queue.workerMethods.runEventPipeline).toHaveBeenCalledWith({
                distinct_id: 'id',
                event: 'event',
                properties: {},
                ip: null,
                now: null,
                sent_at: null,
                site_url: null,
                team_id: 1,
                uuid: 'uuid1',
            })
            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_ingestion',
                expect.any(Date)
            )
        })

        it('does not reproduce if already consuming from overflow', async () => {
            const batch = createBatchWithMultipleEventsWithKeys([captureEndpointEvent])
            batch.batch.topic = KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW
            const consume = jest.spyOn(ConfiguredLimiter, 'consume').mockImplementation(() => false)

            await eachBatchIngestion(batch, queue)

            expect(consume).not.toHaveBeenCalled()
            expect(captureIngestionWarning).not.toHaveBeenCalled()
            expect(queue.pluginsServer.kafkaProducer.queueMessage).not.toHaveBeenCalled()
        })

        it('breaks up by teamId:distinctId for enabled teams', async () => {
            const batch = createBatchWithMultipleEvents([
                { ...captureEndpointEvent, offset: 1, team_id: 3 },
                { ...captureEndpointEvent, offset: 2, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 3, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 4, team_id: 3, distinct_id: 'id2' },
                { ...captureEndpointEvent, offset: 5, team_id: 4 },
                { ...captureEndpointEvent, offset: 6, team_id: 5 },
                { ...captureEndpointEvent, offset: 7 },
                { ...captureEndpointEvent, offset: 8, team_id: 3, distinct_id: 'id2' }, // repeat
                { ...captureEndpointEvent, offset: 9, team_id: 4 },
                { ...captureEndpointEvent, offset: 10, team_id: 4 }, // repeat
                { ...captureEndpointEvent, offset: 11, team_id: 3 },
                { ...captureEndpointEvent, offset: 12 },
                { ...captureEndpointEvent, offset: 13 }, // repeat
            ])

            await eachBatchIngestion(batch, queue)

            // Check the breakpoints in the batches matching repeating teamId:distinctId
            expect(batch.resolveOffset).toBeCalledTimes(6)
            expect(batch.resolveOffset).toHaveBeenCalledWith(1)
            expect(batch.resolveOffset).toHaveBeenCalledWith(2)
            expect(batch.resolveOffset).toHaveBeenCalledWith(7)
            expect(batch.resolveOffset).toHaveBeenCalledWith(9)
            expect(batch.resolveOffset).toHaveBeenCalledWith(12)
            expect(batch.resolveOffset).toHaveBeenCalledWith(13)

            expect(queue.pluginsServer.statsd.histogram).toHaveBeenCalledWith(
                'ingest_event_batching.input_length',
                13,
                {
                    key: 'ingestion',
                }
            )
            expect(queue.pluginsServer.statsd.histogram).toHaveBeenCalledWith('ingest_event_batching.batch_count', 6, {
                key: 'ingestion',
            })
        })
    })
})
