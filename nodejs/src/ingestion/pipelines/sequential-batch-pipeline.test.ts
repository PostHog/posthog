import { Message } from 'node-rdkafka'

import { BaseBatchPipeline } from './base-batch-pipeline'
import { createBatch, createNewBatchPipeline, createNewPipeline } from './helpers'
import { dlq, drop, ok } from './results'
import { SequentialBatchPipeline } from './sequential-batch-pipeline'

describe('SequentialBatchPipeline', () => {
    describe('basic functionality', () => {
        it('should process items sequentially through pipeline', async () => {
            const messages: Message[] = [
                {
                    value: Buffer.from('test1'),
                    topic: 'test',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    size: 5,
                    timestamp: Date.now(),
                    headers: [],
                },
                {
                    value: Buffer.from('test2'),
                    topic: 'test',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    size: 5,
                    timestamp: Date.now(),
                    headers: [],
                },
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            const mockProcessStep = jest.fn().mockImplementation(async (input: { message: Message }) => {
                const value = input.message.value?.toString()
                await Promise.resolve() // Add await to satisfy linter
                return ok({ processed: value })
            })

            const pipeline = new SequentialBatchPipeline(createNewPipeline().pipe(mockProcessStep), rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(mockProcessStep).toHaveBeenCalledTimes(2)
            expect(mockProcessStep).toHaveBeenNthCalledWith(1, { message: messages[0] })
            expect(mockProcessStep).toHaveBeenNthCalledWith(2, { message: messages[1] })
            expect(results).toEqual([
                { result: ok({ processed: 'test1' }), context: expect.objectContaining({ message: messages[0] }) },
                { result: ok({ processed: 'test2' }), context: expect.objectContaining({ message: messages[1] }) },
            ])
        })

        it('should handle empty batch', async () => {
            const rootPipeline = createNewBatchPipeline().build()
            const mockProcessStep = jest.fn().mockImplementation(async (input: { message: Message }) => {
                await Promise.resolve() // Add await to satisfy linter
                return ok(input)
            })

            const pipeline = new SequentialBatchPipeline(createNewPipeline().pipe(mockProcessStep), rootPipeline)

            pipeline.feed([])
            const results = await pipeline.next()

            expect(mockProcessStep).not.toHaveBeenCalled()
            expect(results).toEqual(null)
        })
    })

    describe('sequential processing', () => {
        it('should process each item one by one in order', async () => {
            const messages: Message[] = [
                {
                    value: Buffer.from('1'),
                    topic: 'test',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    size: 1,
                    timestamp: Date.now(),
                    headers: [],
                },
                {
                    value: Buffer.from('2'),
                    topic: 'test',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    size: 1,
                    timestamp: Date.now(),
                    headers: [],
                },
                {
                    value: Buffer.from('3'),
                    topic: 'test',
                    partition: 0,
                    offset: 3,
                    key: Buffer.from('key3'),
                    size: 1,
                    timestamp: Date.now(),
                    headers: [],
                },
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            const processOrder: number[] = []
            const mockProcessStep = jest.fn().mockImplementation(async (input: { message: Message }) => {
                const value = parseInt(input.message.value?.toString() || '0')
                processOrder.push(value)
                await new Promise((resolve) => setTimeout(resolve, 10)) // Small delay to ensure sequential processing
                return ok({ count: value * 2 })
            })

            const pipeline = new SequentialBatchPipeline(createNewPipeline().pipe(mockProcessStep), rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(processOrder).toEqual([1, 2, 3])
            expect(mockProcessStep).toHaveBeenCalledTimes(3)
            expect(results).toEqual([
                { result: ok({ count: 2 }), context: expect.objectContaining({ message: messages[0] }) },
                { result: ok({ count: 4 }), context: expect.objectContaining({ message: messages[1] }) },
                { result: ok({ count: 6 }), context: expect.objectContaining({ message: messages[2] }) },
            ])
        })

        it('should preserve non-success results and only process successful ones', async () => {
            const messages: Message[] = [
                {
                    value: Buffer.from('1'),
                    topic: 'test',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    size: 1,
                    timestamp: Date.now(),
                    headers: [],
                },
                {
                    value: Buffer.from('drop'),
                    topic: 'test',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    size: 4,
                    timestamp: Date.now(),
                    headers: [],
                },
                {
                    value: Buffer.from('3'),
                    topic: 'test',
                    partition: 0,
                    offset: 3,
                    key: Buffer.from('key3'),
                    size: 1,
                    timestamp: Date.now(),
                    headers: [],
                },
                {
                    value: Buffer.from('dlq'),
                    topic: 'test',
                    partition: 0,
                    offset: 4,
                    key: Buffer.from('key4'),
                    size: 3,
                    timestamp: Date.now(),
                    headers: [],
                },
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

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

            const processedValues: { count: number }[] = []
            const mockProcessStep = jest.fn().mockImplementation(async (input: { count: number }) => {
                processedValues.push(input)
                await Promise.resolve() // Add await to satisfy linter
                return ok({ count: input.count * 2 })
            })

            const secondPipeline = new SequentialBatchPipeline(createNewPipeline().pipe(mockProcessStep), firstPipeline)

            secondPipeline.feed(batch)
            const results = await secondPipeline.next()

            expect(processedValues).toEqual([{ count: 1 }, { count: 3 }])
            expect(results).toEqual([
                { result: ok({ count: 2 }), context: expect.objectContaining({ message: messages[0] }) },
                { result: drop('dropped item'), context: expect.objectContaining({ message: messages[1] }) },
                { result: ok({ count: 6 }), context: expect.objectContaining({ message: messages[2] }) },
                {
                    result: dlq('dlq item', new Error('test error')),
                    context: expect.objectContaining({ message: messages[3] }),
                },
            ])
        })
    })

    describe('error handling', () => {
        it('should propagate errors from pipeline processing', async () => {
            const messages: Message[] = [
                {
                    value: Buffer.from('1'),
                    topic: 'test',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    size: 1,
                    timestamp: Date.now(),
                    headers: [],
                },
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            const mockProcessStep = jest.fn().mockImplementation(async (_input: { message: Message }) => {
                await Promise.resolve() // Add await to satisfy linter
                throw new Error('Pipeline processing failed')
            })

            const pipeline = new SequentialBatchPipeline(createNewPipeline().pipe(mockProcessStep), rootPipeline)

            pipeline.feed(batch)
            await expect(pipeline.next()).rejects.toThrow('Pipeline processing failed')
            expect(mockProcessStep).toHaveBeenCalledTimes(1)
        })

        it('should handle errors in individual items without stopping the batch', async () => {
            const messages: Message[] = [
                {
                    value: Buffer.from('1'),
                    topic: 'test',
                    partition: 0,
                    offset: 1,
                    key: Buffer.from('key1'),
                    size: 1,
                    timestamp: Date.now(),
                    headers: [],
                },
                {
                    value: Buffer.from('error'),
                    topic: 'test',
                    partition: 0,
                    offset: 2,
                    key: Buffer.from('key2'),
                    size: 5,
                    timestamp: Date.now(),
                    headers: [],
                },
                {
                    value: Buffer.from('3'),
                    topic: 'test',
                    partition: 0,
                    offset: 3,
                    key: Buffer.from('key3'),
                    size: 1,
                    timestamp: Date.now(),
                    headers: [],
                },
            ]

            const batch = createBatch(messages.map((message) => ({ message })))
            const rootPipeline = createNewBatchPipeline().build()

            const mockProcessStep = jest.fn().mockImplementation(async (input: { message: Message }) => {
                const value = input.message.value?.toString()
                if (value === 'error') {
                    await Promise.resolve() // Add await to satisfy linter
                    throw new Error('Individual item failed')
                }
                await Promise.resolve() // Add await to satisfy linter
                return ok({ processed: value })
            })

            const pipeline = new SequentialBatchPipeline(createNewPipeline().pipe(mockProcessStep), rootPipeline)

            pipeline.feed(batch)
            await expect(pipeline.next()).rejects.toThrow('Individual item failed')
            expect(mockProcessStep).toHaveBeenCalledTimes(2) // Called for first item, then fails on second
        })
    })
})
