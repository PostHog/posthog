import { Message } from 'node-rdkafka'

import { createMockPipeline } from '../../../tests/helpers/mock-pipeline'
import { logger } from '../../utils/logger'
import { OVERFLOW_OUTPUT } from '../common/outputs'
import { BatchPipelineUnwrapper } from './batch-pipeline-unwrapper'
import { BatchPipeline } from './batch-pipeline.interface'
import { DefaultContext, createContext, createNewBatchPipeline, createOkContext } from './helpers'
import { dlq, drop, ok, redirect } from './results'

// Mock the logger
jest.mock('../../utils/logger', () => ({
    logger: {
        warn: jest.fn(),
    },
}))

const mockLogger = logger as jest.Mocked<typeof logger>

describe('BatchPipelineUnwrapper', () => {
    let message: Message

    beforeEach(() => {
        jest.clearAllMocks()

        message = {
            topic: 'test-topic',
            partition: 0,
            offset: 1,
            key: Buffer.from('key'),
            value: Buffer.from('value'),
            timestamp: Date.now(),
        } as Message
    })

    describe('basic functionality', () => {
        it('should unwrap successful results and return values array', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const batchResults = [
                createOkContext({ message, processed: 'test1' }, { message }),
                createOkContext({ message, processed: 'test2' }, { message }),
            ]

            unwrapper.feed(batchResults)
            const results = await unwrapper.next()

            expect(results).toEqual([
                { message, processed: 'test1' },
                { message, processed: 'test2' },
            ])
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })

        it('should return null when batch pipeline returns null', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const results = await unwrapper.next()

            expect(results).toBeNull()
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })

        it('should return empty array when no successful results', async () => {
            const batchResults = [
                createContext(drop<{ message: Message }>('dropped'), { message }),
                createContext(dlq<{ message: Message }>('failed', new Error('test')), { message }),
            ]

            const mockBatchPipeline = createMockPipeline<{ message: Message }>(batchResults)
            const unwrapper = new BatchPipelineUnwrapper(mockBatchPipeline)

            const results = await unwrapper.next()

            expect(results).toEqual([])
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })
    })

    describe('filtering behavior', () => {
        it('should filter out non-OK results and return only successful values', async () => {
            const message2 = { ...message, offset: 2 } as Message
            const message3 = { ...message, offset: 3 } as Message
            const message4 = { ...message, offset: 4 } as Message
            const message5 = { ...message, offset: 5 } as Message

            const batchResults = [
                createContext(ok({ message, processed: 'success1' }), { message }),
                createContext(drop('dropped item'), { message: message2 }),
                createContext(ok({ message, processed: 'success2' }), { message: message3 }),
                createContext(redirect('redirected', OVERFLOW_OUTPUT), { message: message4 }),
                createContext(dlq('failed item', new Error('processing error')), { message: message5 }),
            ]

            const mockBatchPipeline: BatchPipeline<
                { message: Message },
                { message: Message },
                DefaultContext,
                DefaultContext,
                typeof OVERFLOW_OUTPUT
            > = {
                feed: jest.fn(),
                next: jest.fn().mockResolvedValueOnce(batchResults).mockResolvedValueOnce(null),
            }
            const unwrapper = new BatchPipelineUnwrapper(mockBatchPipeline)

            const results = await unwrapper.next()

            expect(results).toEqual([
                { message, processed: 'success1' },
                { message, processed: 'success2' },
            ])
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })

        it('should handle mixed result types correctly', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const batchResults = [
                createOkContext({ message, value: 'string-value' }, { message }),
                createOkContext({ message, value: 42 }, { message }),
                createOkContext({ message, complex: 'object' }, { message }),
            ]

            unwrapper.feed(batchResults)
            const results = await unwrapper.next()

            expect(results).toEqual([
                { message, value: 'string-value' },
                { message, value: 42 },
                { message, complex: 'object' },
            ])
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })
    })

    describe('side effects warning', () => {
        it('should log warning when there are remaining side effects', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const sideEffect1 = Promise.resolve('effect1')
            const sideEffect2 = Promise.resolve('effect2')

            const batchResults = [
                createOkContext({ message, processed: 'test1' }, { message, sideEffects: [sideEffect1] }),
                createOkContext({ message, processed: 'test2' }, { message, sideEffects: [sideEffect2] }),
            ]

            unwrapper.feed(batchResults)
            const results = await unwrapper.next()

            expect(results).toEqual([
                { message, processed: 'test1' },
                { message, processed: 'test2' },
            ])
            expect(mockLogger.warn).toHaveBeenCalledWith(
                'BatchPipelineUnwrapper found 2 remaining side effects that were not handled'
            )
        })

        it('should count side effects from all results including non-OK ones', async () => {
            const sideEffect1 = Promise.resolve('effect1')
            const sideEffect2 = Promise.resolve('effect2')
            const sideEffect3 = Promise.resolve('effect3')

            const batchResults = [
                createOkContext({ message, processed: 'success' }, { message, sideEffects: [sideEffect1] }),
                createContext(drop<{ message: Message }>('dropped'), { message, sideEffects: [sideEffect2] }),
                createContext(dlq<{ message: Message }>('failed', new Error('test')), {
                    message,
                    sideEffects: [sideEffect3],
                }),
            ]

            const mockBatchPipeline = createMockPipeline<{ message: Message }>(batchResults)
            const unwrapper = new BatchPipelineUnwrapper(mockBatchPipeline)

            const results = await unwrapper.next()

            expect(results).toEqual([{ message, processed: 'success' }])
            expect(mockLogger.warn).toHaveBeenCalledWith(
                'BatchPipelineUnwrapper found 3 remaining side effects that were not handled'
            )
        })

        it('should handle multiple side effects on single result', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const sideEffect1 = Promise.resolve('effect1')
            const sideEffect2 = Promise.resolve('effect2')
            const sideEffect3 = Promise.resolve('effect3')

            const batchResults = [
                createOkContext(
                    { message, processed: 'test' },
                    {
                        message,
                        sideEffects: [sideEffect1, sideEffect2, sideEffect3],
                    }
                ),
            ]

            unwrapper.feed(batchResults)
            const results = await unwrapper.next()

            expect(results).toEqual([{ message, processed: 'test' }])
            expect(mockLogger.warn).toHaveBeenCalledWith(
                'BatchPipelineUnwrapper found 3 remaining side effects that were not handled'
            )
        })

        it('should not log warning when no side effects remain', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const batchResults = [
                createOkContext({ message, processed: 'test1' }, { message }),
                createOkContext({ message, processed: 'test2' }, { message }),
            ]

            unwrapper.feed(batchResults)
            const results = await unwrapper.next()

            expect(results).toEqual([
                { message, processed: 'test1' },
                { message, processed: 'test2' },
            ])
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })

        it('should handle empty side effects arrays correctly', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const batchResults = [createOkContext({ message, processed: 'test' }, { message, sideEffects: [] })]

            unwrapper.feed(batchResults)
            const results = await unwrapper.next()

            expect(results).toEqual([{ message, processed: 'test' }])
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })
    })

    describe('feed delegation', () => {
        it('should delegate feed calls to the batch pipeline', () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const feedSpy = jest.spyOn(batchPipeline, 'feed')
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const batchResults = [createOkContext({ message, processed: 'test' }, { message })]

            unwrapper.feed(batchResults)

            expect(feedSpy).toHaveBeenCalledWith(batchResults)
        })
    })

    describe('edge cases', () => {
        it('should handle empty batches', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            unwrapper.feed([])
            const results = await unwrapper.next()

            expect(results).toBeNull()
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })

        it('should handle complex nested object values', async () => {
            const batchPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const unwrapper = new BatchPipelineUnwrapper(batchPipeline)

            const complexValue = {
                message,
                nested: {
                    array: [1, 2, 3],
                    object: { key: 'value' },
                },
                primitives: {
                    string: 'test',
                    number: 42,
                    boolean: true,
                },
            }

            const batchResults = [createOkContext(complexValue, { message })]

            unwrapper.feed(batchResults)
            const results = await unwrapper.next()

            expect(results).toEqual([complexValue])
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })

        it('should preserve result ordering', async () => {
            const batchResults = [
                createOkContext({ message, value: 'first' }, { message }),
                createContext(drop<{ message: Message }>('dropped'), { message }),
                createOkContext({ message, value: 'second' }, { message }),
                createContext(dlq<{ message: Message }>('failed', new Error('test')), { message }),
                createOkContext({ message, value: 'third' }, { message }),
            ]

            const mockBatchPipeline = createMockPipeline<{ message: Message }>(batchResults)
            const unwrapper = new BatchPipelineUnwrapper(mockBatchPipeline)

            const results = await unwrapper.next()

            expect(results).toEqual([
                { message, value: 'first' },
                { message, value: 'second' },
                { message, value: 'third' },
            ])
            expect(mockLogger.warn).not.toHaveBeenCalled()
        })
    })
})
