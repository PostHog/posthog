import { Producer } from 'kafkajs'

import { PluginsServerConfig } from '../../src/types'
import { KafkaProducerWrapper } from '../../src/utils/db/kafka-producer-wrapper'

describe('KafkaProducerWrapper', () => {
    let producer: KafkaProducerWrapper
    let mockKafkaProducer: Producer
    let flushSpy: any

    beforeEach(() => {
        jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:05').getTime())

        mockKafkaProducer = { sendBatch: jest.fn() } as any
        producer = new KafkaProducerWrapper(mockKafkaProducer, undefined, {
            KAFKA_FLUSH_FREQUENCY_MS: 20000,
            KAFKA_PRODUCER_MAX_QUEUE_SIZE: 4,
            KAFKA_MAX_MESSAGE_BATCH_SIZE: 500,
        } as PluginsServerConfig)
        clearInterval(producer.flushInterval)

        flushSpy = jest.spyOn(producer, 'flush')
    })

    describe('queueMessage()', () => {
        it('respects MAX_QUEUE_SIZE', async () => {
            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })
            await producer.queueMessage({
                topic: 'b',
                messages: [{ value: '1'.repeat(30) }],
            })
            await producer.queueMessage({
                topic: 'b',
                messages: [{ value: '1'.repeat(30) }],
            })

            expect(flushSpy).not.toHaveBeenCalled()
            expect(producer.currentBatch.length).toEqual(3)

            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(30) }],
            })

            expect(flushSpy).toHaveBeenCalled()
            expect(producer.currentBatch.length).toEqual(0)
            expect(producer.currentBatchSize).toEqual(0)
            expect(mockKafkaProducer.sendBatch).toHaveBeenCalledWith({
                topicMessages: [expect.anything(), expect.anything(), expect.anything(), expect.anything()],
            })
        })

        it('respects KAFKA_MAX_MESSAGE_BATCH_SIZE', async () => {
            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(400) }],
            })
            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(20) }],
            })
            expect(flushSpy).not.toHaveBeenCalled()
            expect(producer.currentBatch.length).toEqual(2)

            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(40) }],
            })

            expect(flushSpy).toHaveBeenCalled()

            expect(producer.currentBatch.length).toEqual(1)
            expect(producer.currentBatchSize).toBeGreaterThan(40)
            expect(producer.currentBatchSize).toBeLessThan(100)
            expect(mockKafkaProducer.sendBatch).toHaveBeenCalledWith({
                topicMessages: [expect.anything(), expect.anything()],
            })
        })

        it('flushes immediately when message exceeds KAFKA_MAX_MESSAGE_BATCH_SIZE', async () => {
            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10000) }],
            })

            expect(flushSpy).toHaveBeenCalled()

            expect(producer.currentBatch.length).toEqual(0)
            expect(producer.currentBatchSize).toEqual(0)
            expect(mockKafkaProducer.sendBatch).toHaveBeenCalledWith({
                topicMessages: [expect.anything()],
            })
        })

        it('respects KAFKA_FLUSH_FREQUENCY_MS', async () => {
            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:20').getTime())
            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            expect(flushSpy).not.toHaveBeenCalled()
            expect(producer.currentBatch.length).toEqual(2)

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:26').getTime())
            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            expect(flushSpy).toHaveBeenCalled()

            expect(producer.currentBatch.length).toEqual(0)
            expect(producer.lastFlushTime).toEqual(Date.now())
            expect(mockKafkaProducer.sendBatch).toHaveBeenCalledWith({
                topicMessages: [expect.anything(), expect.anything(), expect.anything()],
            })
        })
    })

    describe('flush()', () => {
        it('flushes messages in memory', async () => {
            await producer.queueMessage({
                topic: 'a',
                messages: [{ value: '1'.repeat(10) }],
            })

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27 11:00:15').getTime())

            await producer.flush()

            expect(mockKafkaProducer.sendBatch).toHaveBeenCalledWith({
                topicMessages: [
                    {
                        topic: 'a',
                        messages: [{ value: '1'.repeat(10) }],
                    },
                ],
            })
            expect(producer.currentBatch.length).toEqual(0)
            expect(producer.currentBatchSize).toEqual(0)
            expect(producer.lastFlushTime).toEqual(Date.now())
        })

        it('does nothing if nothing queued', async () => {
            await producer.flush()

            expect(mockKafkaProducer.sendBatch).not.toHaveBeenCalled()
        })
    })
})
