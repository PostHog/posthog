import { CompressionTypes, Producer } from 'kafkajs'

import { PluginsServerConfig } from '../../src/types'
import { KafkaProducerWrapper } from '../../src/utils/db/kafka-producer-wrapper'

jest.setTimeout(1000)

describe('KafkaProducerWrapper', () => {
    let producer: KafkaProducerWrapper
    let mockKafkaProducer: Producer
    let sendBatch: any

    beforeEach(() => {
        jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())
        sendBatch = jest.fn()
        mockKafkaProducer = { sendBatch: sendBatch, disconnect: jest.fn() } as any
    })

    afterEach(async () => {
        await producer?.disconnect()
        jest.useRealTimers()
        sendBatch.mockReset()
    })

    describe('queueMessage()', () => {
        it('respects MAX_QUEUE_SIZE', async () => {
            producer = new KafkaProducerWrapper(mockKafkaProducer, undefined, {
                KAFKA_FLUSH_FREQUENCY_MS: 10000, // Make sure the flush interval doesn't trigger
                KAFKA_PRODUCER_MAX_QUEUE_SIZE: 4, // Set a small queue size
            } as PluginsServerConfig)

            void producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })
            void producer.queueMessage({
                topic: 'b',
                messages: [{ value: '1'.repeat(30) }],
            })
            void producer.queueMessage({
                topic: 'b',
                messages: [{ value: '1'.repeat(30) }],
            })

            // By this stage the producer should still be waiting to fill the
            // message queue to max still.
            expect(sendBatch).not.toBeCalled()

            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(30) }],
            })

            // After the last message, the queue should be full and the producer
            // should have flushed to Kafka.
            expect(sendBatch).toHaveBeenCalledWith({
                compression: CompressionTypes.Snappy,
                topicMessages: [expect.anything(), expect.anything(), expect.anything(), expect.anything()],
            })
        })

        it('respects KAFKA_MAX_MESSAGE_BATCH_SIZE', () => {
            producer = new KafkaProducerWrapper(mockKafkaProducer, undefined, {
                KAFKA_FLUSH_FREQUENCY_MS: 10000, // Make sure the flush interval doesn't trigger
                KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // Set a large queue size that we won't hit
                KAFKA_MAX_MESSAGE_BATCH_SIZE: 500, // Set a small message size that we will hit
            } as PluginsServerConfig)

            void producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(400) }],
            })
            void producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(20) }],
            })

            // We should still be below the batch size at this point
            expect(sendBatch).not.toHaveBeenCalled()

            void producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(40) }],
            })

            // The third message should have pushed us over the batch size, and
            // thus the first two messages should have been sent to Kafka.
            expect(sendBatch).toHaveBeenCalledWith({
                compression: CompressionTypes.Snappy,
                topicMessages: [expect.anything(), expect.anything()],
            })
        })

        it('flushes immediately when message exceeds KAFKA_MAX_MESSAGE_BATCH_SIZE', () => {
            producer = new KafkaProducerWrapper(mockKafkaProducer, undefined, {
                KAFKA_FLUSH_FREQUENCY_MS: 10000, // Make sure the flush interval doesn't trigger
                KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // Set a large queue size that we won't hit
                KAFKA_MAX_MESSAGE_BATCH_SIZE: 500, // Set a small message size that we will hit
            } as PluginsServerConfig)

            void producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10000) }],
            })

            // The message should have been sent immediately, as it exceeds the
            // batch size.
            expect(sendBatch).toHaveBeenCalledWith({
                compression: CompressionTypes.Snappy,
                topicMessages: [expect.anything()],
            })
        })

        it('respects KAFKA_FLUSH_FREQUENCY_MS', () => {
            jest.useFakeTimers({ now: new Date('2020-02-27 11:00:26') })
            producer = new KafkaProducerWrapper(mockKafkaProducer, undefined, {
                KAFKA_FLUSH_FREQUENCY_MS: 1000, // Set a small flush interval
                KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // Set a large queue size that we won't hit
            } as PluginsServerConfig)

            void producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            void producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            expect(sendBatch).not.toHaveBeenCalled()

            jest.advanceTimersByTime(2000)

            // After 2 seconds we should have flushed the messages to Kafka
            expect(sendBatch).toHaveBeenCalledWith({
                compression: CompressionTypes.Snappy,
                topicMessages: [expect.anything(), expect.anything()],
            })
        })

        it('raises on sendBatch error', async () => {
            producer = new KafkaProducerWrapper(mockKafkaProducer, undefined, {
                KAFKA_FLUSH_FREQUENCY_MS: 10000, // Make sure the flush interval doesn't trigger
                KAFKA_PRODUCER_MAX_QUEUE_SIZE: 2, // Set a small queue size that we will hit
            } as PluginsServerConfig)

            sendBatch.mockRejectedValueOnce(new Error('test error'))

            const firstPromise = producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            const secondPromise = producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            await expect(firstPromise).rejects.toThrow('test error')
            await expect(secondPromise).rejects.toThrow('test error')
        })
    })

    describe('flush()', () => {
        it('flushes messages in memory', async () => {
            producer = new KafkaProducerWrapper(mockKafkaProducer, undefined, {
                KAFKA_FLUSH_FREQUENCY_MS: 10000, // Make sure the flush interval doesn't trigger
                KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // Set a large queue size that we won't hit
            } as PluginsServerConfig)

            void producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            // We shouldn't have flushed yet
            expect(sendBatch).not.toHaveBeenCalled()

            await producer.flush()

            // We should have send messages with an explicit call to flush
            expect(sendBatch).toHaveBeenCalledWith({
                compression: CompressionTypes.Snappy,
                topicMessages: [
                    {
                        topic: 'a',
                        messages: [{ value: '1'.repeat(10) }],
                    },
                ],
            })

            sendBatch.mockClear()

            // Another flush should do nothing
            await producer.flush()
            expect(sendBatch).not.toHaveBeenCalled()
        })

        it('does nothing if nothing queued', async () => {
            producer = new KafkaProducerWrapper(mockKafkaProducer, undefined, {
                KAFKA_FLUSH_FREQUENCY_MS: 10000, // Make sure the flush interval doesn't trigger
                KAFKA_PRODUCER_MAX_QUEUE_SIZE: 100, // Set a large queue size that we won't hit
            } as PluginsServerConfig)

            await producer.flush()

            expect(sendBatch).not.toHaveBeenCalled()
        })
    })
})
