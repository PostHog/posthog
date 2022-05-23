import { eachBatch } from '../../../src/main/ingestion-queues/batch-processing/each-batch'
import { eachBatchAsyncHandlers } from '../../../src/main/ingestion-queues/batch-processing/each-batch-async-handlers'
import { eachBatchBuffer } from '../../../src/main/ingestion-queues/batch-processing/each-batch-buffer'
import { eachBatchIngestion } from '../../../src/main/ingestion-queues/batch-processing/each-batch-ingestion'

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
    let batch: any
    let queue: any

    beforeEach(() => {
        batch = {
            batch: {
                partition: 0,
                messages: [
                    {
                        value: JSON.stringify(event),
                    },
                ],
            },
            resolveOffset: jest.fn(),
            heartbeat: jest.fn(),
            commitOffsetsIfNecessary: jest.fn(),
            isRunning: jest.fn(() => true),
            isStale: jest.fn(() => false),
        }

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
            await eachBatch(batch, queue, eachMessage, 'key')

            expect(eachMessage).toHaveBeenCalledWith({ value: JSON.stringify(event) }, queue)
        })

        it('tracks metrics based on the key', async () => {
            const eachMessage = jest.fn()
            await eachBatch(batch, queue, eachMessage, 'my_key')

            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_my_key',
                expect.any(Date)
            )
        })
    })

    describe('eachBatchAsyncHandlers', () => {
        it('calls runAsyncHandlersEventPipeline', async () => {
            await eachBatchAsyncHandlers(batch, queue)

            expect(queue.workerMethods.runAsyncHandlersEventPipeline).toHaveBeenCalledWith(event)
            expect(queue.pluginsServer.statsd.timing).toHaveBeenCalledWith(
                'kafka_queue.each_batch_async_handlers',
                expect.any(Date)
            )
        })
    })

    describe('eachBatchIngestion', () => {
        it('calls runEventPipeline', async () => {
            batch.batch.messages = [{ value: JSON.stringify(captureEndpointEvent) }]
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
    })

    describe('eachBatchBuffer', () => {
        it('eachBatchBuffer triggers sleep for partition if a messages is newer than BUFFER_CONVERSION_SECONDS', async () => {
            const systemDate = new Date(2022, 1, 1, 1, 0, 0, 0)
            jest.useFakeTimers('modern')
            jest.setSystemTime(systemDate)

            // the message is sent at the same time as the system, meaning we sleep for BUFFER_CONVERSION_SECONDS * 1000
            batch.batch.messages[0].timestamp = systemDate

            await expect(eachBatchBuffer(batch, queue)).rejects.toThrow()

            expect(queue.bufferSleep).toHaveBeenCalledWith(60000, 0)

            jest.clearAllTimers()
        })

        it('eachBatchBuffer processes a batch if the messages are older than BUFFER_CONVERSION_SECONDS', async () => {
            const systemDate = new Date(2022, 1, 1, 1, 0, 0, 0)
            jest.useFakeTimers('modern')
            jest.setSystemTime(systemDate)

            batch.batch.messages[0].timestamp = new Date(2020, 1, 1, 1, 0, 0, 0)

            await eachBatchBuffer(batch, queue)

            expect(queue.workerMethods.runBufferEventPipeline).toHaveBeenCalledWith(event)
            expect(queue.bufferSleep).not.toHaveBeenCalled()

            jest.clearAllTimers()
        })
    })
})
