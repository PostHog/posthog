import { Message } from 'node-rdkafka'

import { createTestMessage } from '~/tests/helpers/kafka-message'
import { createMockPipeline } from '~/tests/helpers/mock-pipeline'

import { ChunkPipelineResultWithContext } from './chunk-pipeline.interface'
import { FilterMapChunkPipeline, FilterMapMappingFunction } from './filter-map-chunk-pipeline'
import { createContext, createNewChunkPipeline, createOkContext } from './helpers'
import { dlq, drop, ok } from './results'

describe('FilterMapChunkPipeline', () => {
    let message1: Message
    let message2: Message
    let message3: Message
    let context1: { message: Message }
    let context2: { message: Message }
    let context3: { message: Message }

    beforeEach(() => {
        message1 = createTestMessage({ offset: 1, key: Buffer.from('key1'), value: Buffer.from('value1') })
        message2 = createTestMessage({ offset: 2, key: Buffer.from('key2'), value: Buffer.from('value2') })
        message3 = createTestMessage({ offset: 3, key: Buffer.from('key3'), value: Buffer.from('value3') })

        context1 = { message: message1 }
        context2 = { message: message2 }
        context3 = { message: message3 }
    })

    const identityMapping: FilterMapMappingFunction<string, string, { message: Message }, { message: Message }> = (
        element
    ) => element

    describe('feed', () => {
        it('should delegate to previous pipeline', () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const spy = jest.spyOn(previousPipeline, 'feed')
            const subPipeline = createNewChunkPipeline<string>().build()

            const pipeline = new FilterMapChunkPipeline(previousPipeline, identityMapping, subPipeline)
            const testBatch = [createOkContext('test', context1)]

            pipeline.feed(testBatch)

            expect(spy).toHaveBeenCalledWith(testBatch)
        })
    })

    describe('next', () => {
        it('should return null when previous pipeline is empty', async () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const subPipeline = createNewChunkPipeline<string>().build()

            const pipeline = new FilterMapChunkPipeline(previousPipeline, identityMapping, subPipeline)

            expect(await pipeline.next()).toBeNull()
        })

        it('should pass OK results through mapping and subpipeline', async () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const subPipeline = createNewChunkPipeline<string>().build()

            const pipeline = new FilterMapChunkPipeline(previousPipeline, identityMapping, subPipeline)
            pipeline.feed([createOkContext('hello', context1), createOkContext('world', context2)])

            const result = await pipeline.next()

            expect(result).toEqual([
                { result: ok('hello'), context: expect.objectContaining({ message: message1 }) },
                { result: ok('world'), context: expect.objectContaining({ message: message2 }) },
            ])
        })

        it.each([
            ['dlq', dlq<string>('test error', new Error('test'))],
            ['drop', drop<string>('test drop')],
        ])('should pass %s results through unchanged', async (_name, nonOkResult) => {
            const mockPrevious = createMockPipeline<string>([createContext(nonOkResult, context1)])
            const subPipeline = createNewChunkPipeline<string>().build()

            const pipeline = new FilterMapChunkPipeline(mockPrevious, identityMapping, subPipeline)

            const result = await pipeline.next()

            expect(result).toEqual([{ result: nonOkResult, context: expect.objectContaining({ message: message1 }) }])
        })

        it('should return non-OK results first, then subpipeline results on next call', async () => {
            const subPipeline = createNewChunkPipeline<string>().build()
            const dlqResult = dlq<string>('test error', new Error('test'))

            const mockPrevious = createMockPipeline<string>([
                createOkContext('hello', context1),
                createContext(dlqResult, context2),
                createOkContext('world', context3),
            ])

            const pipeline = new FilterMapChunkPipeline(mockPrevious, identityMapping, subPipeline)

            const result1 = await pipeline.next()
            expect(result1).toEqual([{ result: dlqResult, context: expect.objectContaining({ message: message2 }) }])

            const result2 = await pipeline.next()
            expect(result2).toEqual([
                { result: ok('hello'), context: expect.objectContaining({ message: message1 }) },
                { result: ok('world'), context: expect.objectContaining({ message: message3 }) },
            ])

            expect(await pipeline.next()).toBeNull()
        })

        it('should apply mapping function to transform OK values', async () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const subPipeline = createNewChunkPipeline<string>().build()
            const uppercaseMapping: FilterMapMappingFunction<
                string,
                string,
                { message: Message },
                { message: Message }
            > = (element) => ({
                result: ok(element.result.value.toUpperCase()),
                context: element.context,
            })

            const pipeline = new FilterMapChunkPipeline(previousPipeline, uppercaseMapping, subPipeline)
            pipeline.feed([createOkContext('hello', context1)])

            const result = await pipeline.next()

            expect(result).toEqual([{ result: ok('HELLO'), context: expect.objectContaining({ message: message1 }) }])
        })

        it('should transform context through mapping function for OK results', async () => {
            type InputValue = { value: string; extra: number }

            const previousPipeline = createNewChunkPipeline<InputValue>().build()
            const subPipeline = createNewChunkPipeline<InputValue, { message: Message; extra: number }>().build()
            const contextEnrichingMapping: FilterMapMappingFunction<
                InputValue,
                InputValue,
                { message: Message },
                { message: Message; extra: number }
            > = (element) => ({
                result: element.result,
                context: {
                    ...element.context,
                    extra: element.result.value.extra,
                },
            })

            const pipeline = new FilterMapChunkPipeline(previousPipeline, contextEnrichingMapping, subPipeline)
            pipeline.feed([createOkContext({ value: 'test', extra: 42 }, context1)])

            const result = await pipeline.next()

            expect(result).toHaveLength(1)
            const enrichedContext = result![0].context as { message: Message; extra: number }
            expect(enrichedContext.extra).toBe(42)
        })

        it('should preserve original context for non-OK results', async () => {
            type InputValue = { value: string; extra: number }

            const subPipeline = createNewChunkPipeline<InputValue, { message: Message; extra: number }>().build()
            const dlqResult = dlq<InputValue>('test error', new Error('test'))
            const contextEnrichingMapping: FilterMapMappingFunction<
                InputValue,
                InputValue,
                { message: Message },
                { message: Message; extra: number }
            > = (element) => ({
                result: element.result,
                context: {
                    ...element.context,
                    extra: element.result.value.extra,
                },
            })

            const mockPrevious = createMockPipeline<InputValue>([createContext(dlqResult, context1)])

            const pipeline = new FilterMapChunkPipeline(mockPrevious, contextEnrichingMapping, subPipeline)

            const result = await pipeline.next()

            expect(result).toHaveLength(1)
            // Non-OK results keep original context (no extra field)
            expect(result![0].context).not.toHaveProperty('extra')
            expect(result![0].context.message).toBe(message1)
        })

        it('should process multiple batches sequentially', async () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const subPipeline = createNewChunkPipeline<string>().build()

            const pipeline = new FilterMapChunkPipeline(previousPipeline, identityMapping, subPipeline)

            pipeline.feed([createOkContext('batch1-item', context1)])
            const result1 = await pipeline.next()
            expect(result1).toEqual([
                { result: ok('batch1-item'), context: expect.objectContaining({ message: message1 }) },
            ])

            pipeline.feed([createOkContext('batch2-item', context2)])
            const result2 = await pipeline.next()
            expect(result2).toEqual([
                { result: ok('batch2-item'), context: expect.objectContaining({ message: message2 }) },
            ])

            expect(await pipeline.next()).toBeNull()
        })

        it('should propagate mapping function exceptions', async () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const subPipeline = createNewChunkPipeline<string>().build()
            const error = new Error('mapping failed')
            const throwingMapping: FilterMapMappingFunction<
                string,
                string,
                { message: Message },
                { message: Message }
            > = () => {
                throw error
            }

            const pipeline = new FilterMapChunkPipeline(previousPipeline, throwingMapping, subPipeline)
            pipeline.feed([createOkContext('hello', context1)])

            await expect(pipeline.next()).rejects.toThrow('mapping failed')
        })

        it('should return empty array for empty batch from previous pipeline', async () => {
            const subPipeline = createNewChunkPipeline<string>().build()

            const previousPipeline = {
                feed: jest.fn(),
                next: jest.fn().mockResolvedValueOnce([]).mockResolvedValueOnce(null),
            }

            const pipeline = new FilterMapChunkPipeline(previousPipeline, identityMapping, subPipeline)
            pipeline.feed([])

            // Empty batch should return [] (a valid empty batch), not null (end of stream)
            const result = await pipeline.next()
            expect(result).toEqual([])

            // After the empty batch, next call gets null from previous → returns null
            const result2 = await pipeline.next()
            expect(result2).toBeNull()
        })

        it('should process elements after multiple empty batches from previous pipeline', async () => {
            const subPipeline = createNewChunkPipeline<string>().build()

            const previousPipeline = {
                feed: jest.fn(),
                next: jest
                    .fn()
                    .mockResolvedValueOnce([])
                    .mockResolvedValueOnce([])
                    .mockResolvedValueOnce([])
                    .mockResolvedValueOnce([createContext(ok('hello'), context1)])
                    .mockResolvedValueOnce(null),
            }

            const pipeline = new FilterMapChunkPipeline(previousPipeline, identityMapping, subPipeline)
            pipeline.feed([])

            expect(await pipeline.next()).toEqual([])
            expect(await pipeline.next()).toEqual([])
            expect(await pipeline.next()).toEqual([])

            const result = await pipeline.next()
            expect(result).toEqual([{ result: ok('hello'), context: expect.objectContaining({ message: message1 }) }])

            expect(await pipeline.next()).toBeNull()
        })

        it('should drain subpipeline before fetching from previous pipeline', async () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const subPipelineFeed = jest.fn()
            const subBatches: ChunkPipelineResultWithContext<string, { message: Message }>[] = []
            let subIndex = 0
            const subPipeline = {
                feed(elements: ChunkPipelineResultWithContext<string, { message: Message }>) {
                    subPipelineFeed(elements)
                    for (const el of elements) {
                        subBatches.push([el])
                    }
                },
                next() {
                    if (subIndex >= subBatches.length) {
                        return Promise.resolve(null)
                    }
                    return Promise.resolve(subBatches[subIndex++])
                },
            }

            const pipeline = new FilterMapChunkPipeline(previousPipeline, identityMapping, subPipeline)
            pipeline.feed([createOkContext('item1', context1), createOkContext('item2', context2)])

            const result1 = await pipeline.next()
            expect(result1).toHaveLength(1)
            expect(result1![0].result).toEqual(ok('item1'))

            const result2 = await pipeline.next()
            expect(result2).toHaveLength(1)
            expect(result2![0].result).toEqual(ok('item2'))

            expect(await pipeline.next()).toBeNull()
            expect(subPipelineFeed).toHaveBeenCalledTimes(1)
        })
    })

    describe('error poisoning', () => {
        it('poisons permanently after a source (mapping) error', async () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const subPipeline = createNewChunkPipeline<string>().build()
            const throwingMapping: FilterMapMappingFunction<
                string,
                string,
                { message: Message },
                { message: Message }
            > = () => {
                throw new Error('mapping boom')
            }
            const pipeline = new FilterMapChunkPipeline(previousPipeline, throwingMapping, subPipeline)
            pipeline.feed([createOkContext('hello', context1)])

            await expect(pipeline.next()).rejects.toThrow('mapping boom')
            await expect(pipeline.next()).rejects.toThrow('mapping boom')
        })

        it('poisons permanently after a subpipeline error', async () => {
            const previousPipeline = createNewChunkPipeline<string>().build()
            const subPipeline = {
                feed: jest.fn(),
                next: jest.fn().mockRejectedValueOnce(new Error('sub boom')).mockResolvedValue(null),
            }
            const pipeline = new FilterMapChunkPipeline(previousPipeline, identityMapping, subPipeline)
            pipeline.feed([createOkContext('hello', context1)])

            await expect(pipeline.next()).rejects.toThrow('sub boom')
            await expect(pipeline.next()).rejects.toThrow('sub boom')
        })
    })
})
