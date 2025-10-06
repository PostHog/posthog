import { Message } from 'node-rdkafka'

import { BaseBatchPipeline } from './base-batch-pipeline'
import { createBatch, createNewBatchPipeline } from './helpers'
import { dlq, drop, ok } from './results'

function createTestMessage(overrides: Partial<Message> = {}): Message {
    return {
        value: Buffer.from('test'),
        topic: 'test',
        partition: 0,
        offset: 1,
        key: Buffer.from('key1'),
        size: 4,
        timestamp: Date.now(),
        headers: [],
        ...overrides,
    }
}

describe('BaseBatchPipeline', () => {
    describe('basic functionality', () => {
        it('should process batch through pipeline', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('test1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('test2'), offset: 2 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline()
            const pipeline = new BaseBatchPipeline((items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                {
                    result: ok({ processed: 'test1' }),
                    context: { message: messages[0], lastStep: 'anonymousBatchStep' },
                },
                {
                    result: ok({ processed: 'test2' }),
                    context: { message: messages[1], lastStep: 'anonymousBatchStep' },
                },
            ])
        })

        it('should handle empty batch', async () => {
            const rootPipeline = createNewBatchPipeline()
            const pipeline = new BaseBatchPipeline((items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok(item)))
            }, rootPipeline)

            pipeline.feed([])
            const results = await pipeline.next()

            expect(results).toEqual(null)
        })
    })

    describe('batch operations', () => {
        it('should execute batch step on all successful values', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('2'), offset: 2 }),
                createTestMessage({ value: Buffer.from('3'), offset: 3 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline()
            const pipeline = new BaseBatchPipeline((items: any[]) => {
                return Promise.resolve(
                    items.map((item: any) => ok({ count: parseInt(item.message.value?.toString() || '0') * 2 }))
                )
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                { result: ok({ count: 2 }), context: { message: messages[0], lastStep: 'anonymousBatchStep' } },
                { result: ok({ count: 4 }), context: { message: messages[1], lastStep: 'anonymousBatchStep' } },
                { result: ok({ count: 6 }), context: { message: messages[2], lastStep: 'anonymousBatchStep' } },
            ])
        })

        it('should preserve non-success results and only process successful ones', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('drop'), offset: 2 }),
                createTestMessage({ value: Buffer.from('3'), offset: 3 }),
                createTestMessage({ value: Buffer.from('dlq'), offset: 4 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline()
            const firstPipeline = new BaseBatchPipeline((items: any[]) => {
                return Promise.resolve(
                    items.map((item: any) => {
                        const value = item.message.value?.toString() || ''
                        if (value === 'drop') {
                            return drop('dropped item')
                        }
                        if (value === 'dlq') {
                            return dlq('dlq item', new Error('test error'))
                        }
                        return ok({ count: parseInt(value) })
                    })
                )
            }, rootPipeline)

            const secondPipeline = new BaseBatchPipeline((items: any[]) => {
                expect(items).toEqual([{ count: 1 }, { count: 3 }])
                return Promise.resolve(items.map((item: any) => ok({ count: item.count * 2 })))
            }, firstPipeline)

            secondPipeline.feed(batch)
            const results = await secondPipeline.next()

            expect(results).toEqual([
                { result: ok({ count: 2 }), context: { message: messages[0], lastStep: 'anonymousBatchStep' } },
                { result: drop('dropped item'), context: { message: messages[1], lastStep: 'anonymousBatchStep' } },
                { result: ok({ count: 6 }), context: { message: messages[2], lastStep: 'anonymousBatchStep' } },
                {
                    result: dlq('dlq item', new Error('test error')),
                    context: { message: messages[3], lastStep: 'anonymousBatchStep' },
                },
            ])
        })
    })

    describe('error handling', () => {
        it('should propagate errors from batch operations', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('1'), offset: 1 })]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline()
            const pipeline = new BaseBatchPipeline(() => {
                return Promise.reject(new Error('Batch step failed'))
            }, rootPipeline)

            pipeline.feed(batch)
            await expect(pipeline.next()).rejects.toThrow('Batch step failed')
        })
    })

    describe('step name tracking', () => {
        it('should include step name in context for successful results', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('test1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('test2'), offset: 2 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline()

            function testBatchStep(items: any[]) {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }

            const pipeline = new BaseBatchPipeline(testBatchStep, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                {
                    result: ok({ processed: 'test1' }),
                    context: { message: messages[0], lastStep: 'testBatchStep' },
                },
                {
                    result: ok({ processed: 'test2' }),
                    context: { message: messages[1], lastStep: 'testBatchStep' },
                },
            ])
        })

        it('should use anonymousBatchStep when step has no name', async () => {
            const messages: Message[] = [createTestMessage({ value: Buffer.from('test1'), offset: 1 })]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline()

            const anonymousStep = (items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }

            const pipeline = new BaseBatchPipeline(anonymousStep, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                {
                    result: ok({ processed: 'test1' }),
                    context: { message: messages[0], lastStep: 'anonymousStep' },
                },
            ])
        })

        it('should not update lastStep for failed results', async () => {
            const messages: Message[] = [
                createTestMessage({ value: Buffer.from('test1'), offset: 1 }),
                createTestMessage({ value: Buffer.from('drop'), offset: 2 }),
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline()

            function testBatchStep(items: any[]) {
                return Promise.resolve(
                    items.map((item: any) => {
                        const value = item.message.value?.toString() || ''
                        if (value === 'drop') {
                            return drop('dropped item')
                        }
                        return ok({ processed: value })
                    })
                )
            }

            const pipeline = new BaseBatchPipeline(testBatchStep, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                {
                    result: ok({ processed: 'test1' }),
                    context: { message: messages[0], lastStep: 'testBatchStep' },
                },
                {
                    result: drop('dropped item'),
                    context: { message: messages[1], lastStep: 'testBatchStep' },
                },
            ])
        })
    })
})
