import { eachBatch } from '../../../src/main/ingestion-queues/batch-processing/each-batch'
import { eachBatchAsyncHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-async-handlers'
import { eachBatchBuffer } from '../../../src/main/ingestion-queues/batch-processing/each-batch-buffer'
import { eachBatchIngestion } from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { ClickhouseEventKafka } from '../../../src/types'
import { groupIntoBatches } from '../../../src/utils/utils'

jest.mock('../../../src/utils/status')

const event = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00.000Z',
    event: '$pageview',
    properties: {},
    elementsList: [],
}

const clickhouseEvent: ClickhouseEventKafka = {
    event: '$pageview',
    properties: JSON.stringify({
        $ip: '127.0.0.1',
    }),
    person_properties: null,
    uuid: 'uuid1',
    elements_chain: '',
    timestamp: '2020-02-23 02:15:00.00',
    team_id: 2,
    distinct_id: 'my_id',
    created_at: '2020-02-23T02:15:00Z',
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
            await eachBatch(createBatch(event), queue, eachMessage, groupIntoBatches, 'key')

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
        it('calls runEventPipeline', async () => {
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

    describe('eachBatchBuffer', () => {
        it('eachBatchBuffer triggers sleep for partition if a messages is newer than BUFFER_CONVERSION_SECONDS', async () => {
            const systemDate = new Date(2022, 1, 1, 1, 0, 0, 0)
            jest.useFakeTimers('modern')
            jest.setSystemTime(systemDate)

            // the message is sent at the same time as the system, meaning we sleep for BUFFER_CONVERSION_SECONDS * 1000
            const batch = createBatch(event, systemDate)

            await eachBatchBuffer(batch, queue)

            expect(queue.bufferSleep).toHaveBeenCalledWith(60000, 0, undefined, expect.any(Function))

            jest.clearAllTimers()
        })

        it('eachBatchBuffer processes a batch if the messages are older than BUFFER_CONVERSION_SECONDS', async () => {
            const systemDate = new Date(2022, 1, 1, 1, 0, 0, 0)
            jest.useFakeTimers('modern')
            jest.setSystemTime(systemDate)

            // the message is sent at the same time as the system, meaning we sleep for BUFFER_CONVERSION_SECONDS * 1000
            const batch = createBatch(event, new Date(2020, 1, 1, 1, 0, 0, 0))

            await eachBatchBuffer(batch, queue)

            expect(queue.workerMethods.runBufferEventPipeline).toHaveBeenCalledWith(event)
            expect(queue.bufferSleep).not.toHaveBeenCalled()

            jest.clearAllTimers()
        })
    })
})
