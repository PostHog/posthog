import { Message } from 'node-rdkafka'

import { captureException } from '../../utils/posthog'
import { createNewPipeline, createRetryingPipeline } from './helpers'
import { PipelineResultWithContext } from './pipeline.interface'
import { PipelineResultType, dlq, ok } from './results'
import { RetryingPipeline, RetryingPipelineOptions } from './retrying-pipeline'

jest.setTimeout(1000)

jest.mock('../../utils/posthog', () => ({
    captureException: jest.fn(),
}))

const mockCaptureException = captureException as jest.MockedFunction<typeof captureException>

describe('RetryingPipeline', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('basic functionality', () => {
        it('should process input through inner pipeline successfully', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (input: { message: Message }) => {
                const value = input.message.value?.toString()
                return Promise.resolve(ok({ processed: value }))
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const retryingPipeline = createRetryingPipeline(innerPipeline)
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const result = await retryingPipeline.process(input)

            expect(mockProcessStep).toHaveBeenCalledTimes(1)
            expect(mockProcessStep).toHaveBeenCalledWith({ message })
            expect(result).toEqual({
                result: ok({ processed: 'test' }),
                context: expect.objectContaining({ message }),
            })
        })
    })

    describe('retry behavior', () => {
        it('should retry on retriable errors and log errors after all retries', async () => {
            let callCount = 0
            const mockProcessStep = jest.fn().mockImplementation(async (input: { message: Message }) => {
                callCount++
                if (callCount < 3) {
                    const error = new Error('Retriable error')
                    ;(error as any).isRetriable = true
                    return Promise.reject(error)
                }
                const value = input.message.value?.toString()
                return ok({ processed: value })
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const retryingPipeline = createRetryingPipeline(innerPipeline, { tries: 3, sleepMs: 150 })
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const processPromise = retryingPipeline.process(input)

            const result = await processPromise

            expect(callCount).toBe(3)
            expect(mockCaptureException).not.toHaveBeenCalled() // Should not capture retriable errors
            expect(result).toEqual({
                result: ok({ processed: 'test' }),
                context: expect.objectContaining({ message }),
            })
        })

        it('should log errors when all retries are exhausted', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (_input: { message: Message }) => {
                const error = new Error('Retriable error that exhausts retries')
                ;(error as any).isRetriable = true
                return Promise.reject(error)
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const retryingPipeline = createRetryingPipeline(innerPipeline, { tries: 3, sleepMs: 200 })
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const processPromise = retryingPipeline.process(input)

            await expect(processPromise).rejects.toThrow('Retriable error that exhausts retries')
            expect(mockProcessStep).toHaveBeenCalledTimes(3) // Called 3 times (initial + 2 retries)
            expect(mockCaptureException).not.toHaveBeenCalled() // Should not capture retriable errors
        })

        it('should not retry on non-retriable errors and return DLQ result', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (_input: { message: Message }) => {
                const error = new Error('Non-retriable error')
                ;(error as any).isRetriable = false
                return Promise.reject(error)
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const retryingPipeline = createRetryingPipeline(innerPipeline, { tries: 5, sleepMs: 50 })
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const result = await retryingPipeline.process(input)

            expect(mockProcessStep).toHaveBeenCalledTimes(1)
            expect(mockCaptureException).toHaveBeenCalledTimes(1)
            expect(mockCaptureException).toHaveBeenCalledWith(expect.any(Error))
            expect(result.result.type).toBe(PipelineResultType.DLQ)
            if (result.result.type === PipelineResultType.DLQ) {
                expect(result.result.reason).toBe('Processing error - non-retriable')
            }
            expect(result.context).toEqual(expect.objectContaining({ message }))
        })

        it('should treat errors without isRetriable property as retriable', async () => {
            let callCount = 0
            const mockProcessStep = jest.fn().mockImplementation(async (input: { message: Message }) => {
                callCount++
                if (callCount < 2) {
                    const error = new Error('Error without isRetriable property')
                    // No isRetriable property set
                    throw error
                }
                const value = input.message.value?.toString()
                return Promise.resolve(ok({ processed: value }))
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const retryingPipeline = createRetryingPipeline(innerPipeline, { tries: 2, sleepMs: 75 })
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const processPromise = retryingPipeline.process(input)

            const result = await processPromise

            expect(callCount).toBe(2)
            expect(mockCaptureException).not.toHaveBeenCalled() // Should not capture retriable errors
            expect(result).toEqual({
                result: ok({ processed: 'test' }),
                context: expect.objectContaining({ message }),
            })
        })

        it('should propagate DLQ results without retrying', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (_input: { message: Message }) => {
                return Promise.resolve(dlq('DLQ reason', new Error('test error')))
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const retryingPipeline = createRetryingPipeline(innerPipeline, { tries: 4, sleepMs: 300 })
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const result = await retryingPipeline.process(input)

            expect(result).toEqual({
                result: {
                    type: PipelineResultType.DLQ,
                    reason: 'DLQ reason',
                    error: expect.any(Error),
                },
                context: expect.objectContaining({ message }),
            })
        })
    })

    describe('createRetryingPipeline helper', () => {
        it('should create a retrying pipeline', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (input: { message: Message }) => {
                const value = input.message.value?.toString()
                return Promise.resolve(ok({ processed: value }))
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const retryingPipeline = createRetryingPipeline(innerPipeline, { tries: 1, sleepMs: 25 })
            expect(retryingPipeline).toBeInstanceOf(RetryingPipeline)

            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const result = await retryingPipeline.process(input)

            expect(mockProcessStep).toHaveBeenCalledTimes(1)
            expect(result).toEqual({
                result: ok({ processed: 'test' }),
                context: expect.objectContaining({ message }),
            })
        })
    })

    describe('retry configuration options', () => {
        it('should use custom retry count', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (_input: { message: Message }) => {
                const error = new Error('Retriable error')
                ;(error as any).isRetriable = true
                return Promise.reject(error)
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const options: RetryingPipelineOptions = { tries: 2, sleepMs: 80 }
            const retryingPipeline = createRetryingPipeline(innerPipeline, options)
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const processPromise = retryingPipeline.process(input)

            await expect(processPromise).rejects.toThrow('Retriable error')
            expect(mockProcessStep).toHaveBeenCalledTimes(2) // Called 2 times (initial + 1 retry)
        })

        it('should use custom sleep duration', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (_input: { message: Message }) => {
                const error = new Error('Retriable error')
                ;(error as any).isRetriable = true
                return Promise.reject(error)
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const options: RetryingPipelineOptions = { tries: 2, sleepMs: 50 }
            const retryingPipeline = createRetryingPipeline(innerPipeline, options)
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const processPromise = retryingPipeline.process(input)

            await expect(processPromise).rejects.toThrow('Retriable error')
            expect(mockProcessStep).toHaveBeenCalledTimes(2) // Called 2 times (initial + 1 retry)
        })

        it('should use default values when no options provided', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (_input: { message: Message }) => {
                const error = new Error('Retriable error')
                ;(error as any).isRetriable = true
                return Promise.reject(error)
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const retryingPipeline = createRetryingPipeline(innerPipeline) // No options - uses defaults
            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const processPromise = retryingPipeline.process(input)

            await expect(processPromise).rejects.toThrow('Retriable error')
            expect(mockProcessStep).toHaveBeenCalledTimes(3) // Default retry count of 3
        })

        it('should use createRetryingPipeline helper with options', async () => {
            const mockProcessStep = jest.fn().mockImplementation(async (_input: { message: Message }) => {
                const error = new Error('Retriable error')
                ;(error as any).isRetriable = true
                return Promise.reject(error)
            })

            const innerPipeline = createNewPipeline().pipe(mockProcessStep)
            const options: RetryingPipelineOptions = { tries: 2, sleepMs: 120 }
            const retryingPipeline = createRetryingPipeline(innerPipeline, options)
            expect(retryingPipeline).toBeInstanceOf(RetryingPipeline)

            const message: Message = {
                value: Buffer.from('test'),
                topic: 'test',
                partition: 0,
                offset: 1,
                key: Buffer.from('key'),
                size: 4,
                timestamp: Date.now(),
                headers: [],
            }

            const input: PipelineResultWithContext<{ message: Message }> = {
                result: ok({ message }),
                context: { message },
            }

            const processPromise = retryingPipeline.process(input)

            await expect(processPromise).rejects.toThrow('Retriable error')
            expect(mockProcessStep).toHaveBeenCalledTimes(2) // Called 2 times (initial + 1 retry)
        })
    })
})
