import { KAFKA_EVENTS_PLUGIN_INGESTION, KAFKA_EVENTS_PLUGIN_INGESTION_OVERFLOW } from '../../../src/config/kafka-topics'
import { eachBatch } from '../../../src/main/ingestion-queues/batch-processing/each-batch'
import { eachBatchAsyncHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-async-handlers'
import {
    eachBatchIngestion,
    eachBatchParallelIngestion,
    IngestionOverflowMode,
    splitIngestionBatch,
} from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import {
    ClickHouseTimestamp,
    ClickHouseTimestampSecondPrecision,
    ISOTimestamp,
    PostIngestionEvent,
    RawClickHouseEvent,
} from '../../../src/types'
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
    person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
    person_created_at: '2020-02-20T02:15:00.000Z' as ISOTimestamp,
    person_properties: {},
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
    person_id: 'F99FA0A1-E0C2-4CFE-A09A-4C3C4327A4CC',
    person_created_at: '2020-02-20 02:15:00' as ClickHouseTimestampSecondPrecision, // Match createEvent ts format
    person_properties: '{}',
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
            },
            workerMethods: {
                runAsyncHandlersEventPipeline: jest.fn(),
                runEventPipeline: jest.fn(),
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

    describe('eachBatchParallelIngestion', () => {
        it('calls runEventPipeline', async () => {
            const batch = createBatch(captureEndpointEvent)
            await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Disabled)

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
                'kafka_queue.each_batch_parallel_ingestion',
                expect.any(Date)
            )
        })

        it('batches events by team or token and distinct_id', () => {
            const batch = createBatchWithMultipleEvents([
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'b' },
                { ...captureEndpointEvent, team_id: 4, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 4, distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: 4, distinct_id: 'b' },
                { ...captureEndpointEvent, team_id: undefined, token: 'tok', distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: undefined, token: 'tok', distinct_id: 'a' },
                { ...captureEndpointEvent, team_id: undefined, token: 'tok', distinct_id: 'b' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'c' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'b' },
                { ...captureEndpointEvent, team_id: 3, distinct_id: 'a' },
            ])
            const stats = new Map()
            for (const group of splitIngestionBatch(batch.batch.messages, IngestionOverflowMode.Disabled).toProcess) {
                const key = `${group[0].team_id}:${group[0].token}:${group[0].distinct_id}`
                for (const event of group) {
                    expect(`${event.team_id}:${event.token}:${event.distinct_id}`).toEqual(key)
                }
                stats.set(key, group.length)
            }
            expect(stats.size).toEqual(7)
            expect(stats).toEqual(
                new Map([
                    ['3:undefined:a', 3],
                    ['3:undefined:b', 2],
                    ['3:undefined:c', 1],
                    ['4:undefined:a', 2],
                    ['4:undefined:b', 1],
                    ['undefined:tok:a', 2],
                    ['undefined:tok:b', 1],
                ])
            )
        })

        it('batches events but commits offsets only once', async () => {
            const batch = createBatchWithMultipleEvents([
                { ...captureEndpointEvent, offset: 1, team_id: 3 },
                { ...captureEndpointEvent, offset: 2, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 3, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 4, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 5, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 6, team_id: 3, distinct_id: 'id2' },
                { ...captureEndpointEvent, offset: 7, team_id: 4 },
                { ...captureEndpointEvent, offset: 8, team_id: 5 },
                { ...captureEndpointEvent, offset: 9, team_id: 5 }, // repeat
                { ...captureEndpointEvent, offset: 10, team_id: 3, distinct_id: 'id2' }, // repeat
                { ...captureEndpointEvent, offset: 11, team_id: 8 },
                { ...captureEndpointEvent, offset: 12, team_id: 4 }, // repeat
                { ...captureEndpointEvent, offset: 13, team_id: 3 }, // repeat
                { ...captureEndpointEvent, offset: 14, team_id: 5 }, // repeat
            ])

            await eachBatchParallelIngestion(batch, queue, IngestionOverflowMode.Disabled)
            expect(batch.resolveOffset).toBeCalledTimes(1)
            expect(batch.resolveOffset).toHaveBeenCalledWith(14)
            expect(queue.workerMethods.runEventPipeline).toHaveBeenCalledTimes(14)
            expect(queue.pluginsServer.statsd.histogram).toHaveBeenCalledWith(
                'ingest_event_batching.input_length',
                14,
                {
                    key: 'ingestion',
                }
            )
            expect(queue.pluginsServer.statsd.histogram).toHaveBeenCalledWith('ingest_event_batching.batch_count', 5, {
                key: 'ingestion',
            })
        })
    })
})
