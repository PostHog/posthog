import { Message } from 'node-rdkafka'

import { createBatch, createNewBatchPipeline } from './helpers'
import { dlq, drop, ok } from './results'
import { SequentialBatchPipeline } from './sequential-batch-pipeline'

describe('SequentialBatchPipeline', () => {
    describe('basic functionality', () => {
        it('should process batch through pipeline', async () => {
            const messages: Message[] = [
                { value: Buffer.from('test1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('test2'), topic: 'test', partition: 0, offset: 2 } as Message,
            ]

            const batch = createBatch(messages)
            const rootPipeline = createNewBatchPipeline()
            const pipeline = new SequentialBatchPipeline((items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok({ processed: item.message.value?.toString() })))
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                { result: ok({ processed: 'test1' }), context: { message: messages[0] } },
                { result: ok({ processed: 'test2' }), context: { message: messages[1] } },
            ])
        })

        it('should handle empty batch', async () => {
            const rootPipeline = createNewBatchPipeline()
            const pipeline = new SequentialBatchPipeline((items: any[]) => {
                return Promise.resolve(items.map((item: any) => ok(item)))
            }, rootPipeline)

            pipeline.feed([])
            const results = await pipeline.next()

            expect(results).toEqual(null)
        })
    })

    describe('pipe() - batch operations', () => {
        it('should execute batch step on all successful values', async () => {
            const messages: Message[] = [
                { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('2'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            const batch = createBatch(messages)
            const rootPipeline = createNewBatchPipeline()
            const pipeline = new SequentialBatchPipeline((items: any[]) => {
                return Promise.resolve(
                    items.map((item: any) => ok({ count: parseInt(item.message.value?.toString() || '0') * 2 }))
                )
            }, rootPipeline)

            pipeline.feed(batch)
            const results = await pipeline.next()

            expect(results).toEqual([
                { result: ok({ count: 2 }), context: { message: messages[0] } },
                { result: ok({ count: 4 }), context: { message: messages[1] } },
                { result: ok({ count: 6 }), context: { message: messages[2] } },
            ])
        })

        it('should preserve non-success results and only process successful ones', async () => {
            const messages: Message[] = [
                { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('drop'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('3'), topic: 'test', partition: 0, offset: 3 } as Message,
                { value: Buffer.from('dlq'), topic: 'test', partition: 0, offset: 4 } as Message,
            ]

            const batch = createBatch(messages)
            const rootPipeline = createNewBatchPipeline()
            const firstPipeline = new SequentialBatchPipeline((items: any[]) => {
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

            const secondPipeline = new SequentialBatchPipeline((items: any[]) => {
                // Should only receive successful items
                expect(items).toEqual([{ count: 1 }, { count: 3 }])
                return Promise.resolve(items.map((item: any) => ok({ count: item.count * 2 })))
            }, firstPipeline)

            secondPipeline.feed(batch)
            const results = await secondPipeline.next()

            expect(results).toEqual([
                { result: ok({ count: 2 }), context: { message: messages[0] } },
                { result: drop('dropped item'), context: { message: messages[1] } },
                { result: ok({ count: 6 }), context: { message: messages[2] } },
                { result: dlq('dlq item', new Error('test error')), context: { message: messages[3] } },
            ])
        })
    })

    describe('pipeConcurrently() - concurrent individual processing', () => {
        it('should process each item concurrently', async () => {
            const messages: Message[] = [
                { value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('2'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('3'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            const batch = createBatch(messages)
            const processor = {
                async process(input: any) {
                    await new Promise((resolve) => setTimeout(resolve, 1))
                    const count = parseInt(input.result.value.message.value?.toString() || '0')
                    return { result: ok({ count: count * 2 }), context: input.context }
                },
            }

            const pipeline = createNewBatchPipeline().pipeConcurrently(processor)

            pipeline.feed(batch)

            // Collect all results by calling next() until it returns null
            const allResults = []
            let result = await pipeline.next()
            while (result !== null) {
                allResults.push(...result) // Flatten the array
                result = await pipeline.next()
            }

            expect(allResults).toEqual([
                { result: ok({ count: 2 }), context: { message: messages[0] } },
                { result: ok({ count: 4 }), context: { message: messages[1] } },
                { result: ok({ count: 6 }), context: { message: messages[2] } },
            ])
        })

        it('should preserve order despite concurrent execution', async () => {
            const messages: Message[] = [
                { value: Buffer.from('30'), topic: 'test', partition: 0, offset: 1 } as Message,
                { value: Buffer.from('10'), topic: 'test', partition: 0, offset: 2 } as Message,
                { value: Buffer.from('20'), topic: 'test', partition: 0, offset: 3 } as Message,
            ]

            const batch = createBatch(messages)
            const processor = {
                async process(input: any) {
                    const delay = parseInt(input.result.value.message.value?.toString() || '0')
                    await new Promise((resolve) => setTimeout(resolve, delay))
                    return { result: ok({ processed: delay }), context: input.context }
                },
            }

            const pipeline = createNewBatchPipeline().pipeConcurrently(processor)

            pipeline.feed(batch)

            // Collect all results by calling next() until it returns null
            const allResults = []
            let result = await pipeline.next()
            while (result !== null) {
                allResults.push(...result) // Flatten the array
                result = await pipeline.next()
            }

            expect(allResults).toEqual([
                { result: ok({ processed: 30 }), context: { message: messages[0] } },
                { result: ok({ processed: 10 }), context: { message: messages[1] } },
                { result: ok({ processed: 20 }), context: { message: messages[2] } },
            ])
        })
    })

    describe('error handling', () => {
        it('should propagate errors from batch operations', async () => {
            const messages: Message[] = [{ value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message]

            const batch = createBatch(messages)
            const rootPipeline = createNewBatchPipeline()
            const pipeline = new SequentialBatchPipeline(() => {
                return Promise.reject(new Error('Batch step failed'))
            }, rootPipeline)

            pipeline.feed(batch)
            await expect(pipeline.next()).rejects.toThrow('Batch step failed')
        })

        it('should propagate errors from concurrent operations', async () => {
            const messages: Message[] = [{ value: Buffer.from('1'), topic: 'test', partition: 0, offset: 1 } as Message]

            const batch = createBatch(messages)
            const processor = {
                process() {
                    return Promise.reject(new Error('Concurrent step failed'))
                },
            }

            const pipeline = createNewBatchPipeline().pipeConcurrently(processor)

            pipeline.feed(batch)
            await expect(pipeline.next()).rejects.toThrow('Concurrent step failed')
        })
    })
})
