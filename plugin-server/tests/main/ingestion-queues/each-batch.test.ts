import { eachBatch } from '../../../src/main/ingestion-queues/batch-processing/each-batch'
import { eachBatchAsyncHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-async-handlers'
import { eachBatchBuffer } from '../../../src/main/ingestion-queues/batch-processing/each-batch-buffer'
import { eachBatchIngestion } from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'
import { ClickHouseEvent } from '../../../src/types'
import { groupIntoBatches } from '../../../src/utils/utils'

jest.mock('../../../src/utils/status')

const event = {
    eventUuid: 'uuid1',
    distinctId: 'my_id',
    ip: '127.0.0.1',
    teamId: 2,
    timestamp: '2020-02-23T02:15:00Z',
    event: '$pageview',
    properties: {},
    elementsList: [],
}

const clickhouseEvent: ClickHouseEvent = {
    event: '$pageview',
    properties: {
        $ip: '127.0.0.1',
    },
    uuid: 'uuid1',
    elements_chain: '',
    timestamp: '2020-02-23T02:15:00Z',
    team_id: 2,
    distinct_id: 'my_id',
    created_at: '2020-02-23T02:15:00Z',
    person_properties: {},
    group0_properties: {},
    group1_properties: {},
    group2_properties: {},
    group3_properties: {},
    group4_properties: {},
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
                },
                ingestionBatchBreakupByDistinctIdTeams: new Set(),
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
                properties: clickhouseEvent.properties,
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
                { ...captureEndpointEvent, offset: 1 },
                { ...captureEndpointEvent, offset: 2, team_id: 3 },
                { ...captureEndpointEvent, offset: 3, team_id: 3, distinct_id: 'id2' },
                { ...captureEndpointEvent, offset: 4, team_id: 4 },
                { ...captureEndpointEvent, offset: 5, team_id: 3 },
                { ...captureEndpointEvent, offset: 6 },
            ])
            queue.pluginsServer.ingestionBatchBreakupByDistinctIdTeams.add(3)
            queue.pluginsServer.ingestionBatchBreakupByDistinctIdTeams.add(4)

            await eachBatchIngestion(batch, queue)

            expect(batch.resolveOffset).toBeCalledTimes(2)
            expect(batch.resolveOffset).toHaveBeenCalledWith(4) // 5 was the first repeating
            expect(batch.resolveOffset).toHaveBeenCalledWith(6) // we get the last two in the batch together
        })
    })

    describe('eachBatchBuffer', () => {
        it('eachBatchBuffer triggers sleep for partition if a messages is newer than BUFFER_CONVERSION_SECONDS', async () => {
            const systemDate = new Date(2022, 1, 1, 1, 0, 0, 0)
            jest.useFakeTimers('modern')
            jest.setSystemTime(systemDate)

            // the message is sent at the same time as the system, meaning we sleep for BUFFER_CONVERSION_SECONDS * 1000
            const batch = createBatch(event, systemDate)

            await expect(eachBatchBuffer(batch, queue)).rejects.toThrow()

            expect(queue.bufferSleep).toHaveBeenCalledWith(60000, 0)

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
