import { Message } from 'node-rdkafka'

import { createBatch, createContext, createNewBatchPipeline } from './helpers'
import { sideEffectResultCounter } from './metrics'
import { dlq, drop, ok } from './results'
import {
    PromiseSchedulerInterface,
    SideEffectHandlingConfig,
    SideEffectHandlingPipeline,
} from './side-effect-handling-pipeline'

// Mock the metrics module
jest.mock('./metrics', () => ({
    sideEffectResultCounter: {
        labels: jest.fn().mockReturnThis(),
        inc: jest.fn(),
    },
}))

const mockSideEffectResultCounter = jest.mocked(sideEffectResultCounter)

describe('SideEffectHandlingPipeline', () => {
    let mockPromiseScheduler: jest.Mocked<PromiseSchedulerInterface>
    let message: Message

    beforeEach(() => {
        jest.clearAllMocks()

        mockPromiseScheduler = {
            schedule: jest.fn().mockImplementation((promise) => promise),
        }

        message = {
            topic: 'test-topic',
            partition: 0,
            offset: 1,
            key: Buffer.from('key'),
            value: Buffer.from('value'),
            timestamp: Date.now(),
        } as Message
    })

    describe('feed', () => {
        it('should delegate to sub-pipeline', () => {
            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const spy = jest.spyOn(subPipeline, 'feed')
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler)

            const testBatch = createBatch([{ message }])

            pipeline.feed(testBatch)

            expect(spy).toHaveBeenCalledWith(testBatch)
        })
    })

    describe('next', () => {
        it('should return null when sub-pipeline returns null', async () => {
            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler)

            const result = await pipeline.next()
            expect(result).toBeNull()
        })

        it('should process results with no side effects', async () => {
            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler)

            const batch = createBatch([{ message }])
            pipeline.feed(batch)

            const result = await pipeline.next()

            expect(result).toEqual([{ result: ok({ message }), context: { message, sideEffects: [], warnings: [] } }])
            expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        })

        it('should await side effects and clear them from context', async () => {
            let sideEffectResolved = false
            const sideEffectPromise = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffectResolved = true
                    resolve()
                }, 10)
            })

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            // Manually create batch with side effects
            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [sideEffectPromise] })]

            pipeline.feed(batchWithSideEffects)
            const result = await pipeline.next()

            expect(sideEffectResolved).toBe(true)
            expect(result).toEqual([createContext(ok({ message }), { message })])
            expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        })

        it('should handle multiple side effects', async () => {
            let sideEffect1Resolved = false
            let sideEffect2Resolved = false

            const sideEffectPromise1 = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffect1Resolved = true
                    resolve()
                }, 10)
            })

            const sideEffectPromise2 = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffect2Resolved = true
                    resolve()
                }, 20)
            })

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [
                createContext(ok({ message }), { message, sideEffects: [sideEffectPromise1, sideEffectPromise2] }),
            ]

            pipeline.feed(batchWithSideEffects)

            const result = await pipeline.next()

            expect(sideEffect1Resolved).toBe(true)
            expect(sideEffect2Resolved).toBe(true)
            expect(result).toEqual([createContext(ok({ message }), { message })])
            expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        })

        it('should handle side effects across multiple results', async () => {
            let sideEffect1Resolved = false
            let sideEffect2Resolved = false

            const sideEffectPromise1 = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffect1Resolved = true
                    resolve()
                }, 10)
            })

            const sideEffectPromise2 = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffect2Resolved = true
                    resolve()
                }, 20)
            })

            const message2 = { ...message, offset: 2 } as Message

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [
                createContext(ok({ message }), { message, sideEffects: [sideEffectPromise1] }),
                createContext(ok({ message: message2 }), { message: message2, sideEffects: [sideEffectPromise2] }),
            ]

            pipeline.feed(batchWithSideEffects)

            const result = await pipeline.next()

            expect(sideEffect1Resolved).toBe(true)
            expect(sideEffect2Resolved).toBe(true)
            expect(result).toEqual([
                createContext(ok({ message }), { message }),
                createContext(ok({ message: message2 }), { message: message2 }),
            ])
            expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        })

        it('should handle failed side effects gracefully', async () => {
            const failingSideEffect = Promise.reject(new Error('Side effect failed'))

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [failingSideEffect] })]

            pipeline.feed(batchWithSideEffects)

            // Should not throw even if side effect fails
            const result = await pipeline.next()

            expect(result).toEqual([createContext(ok({ message }), { message })])
            expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        })

        it('should preserve non-ok results and clear their side effects', async () => {
            let sideEffectResolved = false
            const sideEffectPromise = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffectResolved = true
                    resolve()
                }, 10)
            })

            const dropResult = drop<{ message: Message }>('test drop')
            const dlqResult = dlq<{ message: Message }>('test dlq', new Error('test error'))

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [
                createContext(dropResult, { message, sideEffects: [sideEffectPromise] }),
                createContext(dlqResult, { message, sideEffects: [sideEffectPromise] }),
            ]

            pipeline.feed(batchWithSideEffects)

            const result = await pipeline.next()

            expect(sideEffectResolved).toBe(true)
            expect(result).toEqual([createContext(dropResult, { message }), createContext(dlqResult, { message })])
            expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        })

        it('should use promise scheduler when not awaiting side effects', async () => {
            const sideEffectPromise = Promise.resolve('done')

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler)

            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [sideEffectPromise] })]

            pipeline.feed(batchWithSideEffects)

            await pipeline.next()

            expect(mockPromiseScheduler.schedule).toHaveBeenCalledWith(sideEffectPromise)
        })

        it('should not use promise scheduler when awaiting side effects', async () => {
            const sideEffectPromise = Promise.resolve('done')

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [sideEffectPromise] })]

            pipeline.feed(batchWithSideEffects)

            await pipeline.next()

            expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        })
    })

    describe('configuration', () => {
        it('should not await side effects by default (await: false)', async () => {
            let sideEffectResolved = false
            const sideEffectPromise = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffectResolved = true
                    resolve()
                }, 50) // Longer delay to test async behavior
            })

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler) // Default config

            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [sideEffectPromise] })]

            pipeline.feed(batchWithSideEffects)
            const result = await pipeline.next()

            // Should return immediately without waiting
            expect(sideEffectResolved).toBe(false)
            expect(result).toEqual([createContext(ok({ message }), { message })])
            expect(mockPromiseScheduler.schedule).toHaveBeenCalledWith(sideEffectPromise)

            // Wait a bit and check that the side effect is still scheduled
            await new Promise((resolve) => setTimeout(resolve, 100))
            expect(sideEffectResolved).toBe(true)
        })

        it('should await side effects when config.await is true', async () => {
            let sideEffectResolved = false
            const sideEffectPromise = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffectResolved = true
                    resolve()
                }, 10)
            })

            const config: SideEffectHandlingConfig = { await: true }
            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [sideEffectPromise] })]

            pipeline.feed(batchWithSideEffects)
            const result = await pipeline.next()

            // Should have waited for side effect to complete
            expect(sideEffectResolved).toBe(true)
            expect(result).toEqual([createContext(ok({ message }), { message })])
            expect(mockPromiseScheduler.schedule).not.toHaveBeenCalled()
        })

        it('should not await side effects when config.await is false', async () => {
            let sideEffectResolved = false
            const sideEffectPromise = new Promise<void>((resolve) => {
                setTimeout(() => {
                    sideEffectResolved = true
                    resolve()
                }, 50) // Longer delay to test async behavior
            })

            const config: SideEffectHandlingConfig = { await: false }
            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [sideEffectPromise] })]

            pipeline.feed(batchWithSideEffects)
            const result = await pipeline.next()

            // Should return immediately without waiting
            expect(sideEffectResolved).toBe(false)
            expect(result).toEqual([createContext(ok({ message }), { message })])
            expect(mockPromiseScheduler.schedule).toHaveBeenCalledWith(sideEffectPromise)

            // Wait a bit and check that the side effect is still scheduled
            await new Promise((resolve) => setTimeout(resolve, 100))
            expect(sideEffectResolved).toBe(true)
        })

        it('should still schedule side effects even when not awaiting', async () => {
            const sideEffectPromise = Promise.resolve('done')

            const config: SideEffectHandlingConfig = { await: false }
            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [sideEffectPromise] })]

            pipeline.feed(batchWithSideEffects)
            await pipeline.next()

            expect(mockPromiseScheduler.schedule).toHaveBeenCalledWith(sideEffectPromise)
        })
    })

    describe('metrics tracking', () => {
        it('should track successful side effects when await is true', async () => {
            const successfulSideEffect1 = Promise.resolve('success1')
            const successfulSideEffect2 = Promise.resolve('success2')

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [
                createContext(ok({ message }), {
                    message,
                    sideEffects: [successfulSideEffect1, successfulSideEffect2],
                }),
            ]

            pipeline.feed(batchWithSideEffects)
            await pipeline.next()

            expect(mockSideEffectResultCounter.labels).toHaveBeenCalledWith('ok')
            expect(mockSideEffectResultCounter.inc).toHaveBeenCalledTimes(2)
        })

        it('should track failed side effects when await is true', async () => {
            const failingSideEffect1 = Promise.reject(new Error('fail1'))
            const failingSideEffect2 = Promise.reject(new Error('fail2'))

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [
                createContext(ok({ message }), { message, sideEffects: [failingSideEffect1, failingSideEffect2] }),
            ]

            pipeline.feed(batchWithSideEffects)
            await pipeline.next()

            expect(mockSideEffectResultCounter.labels).toHaveBeenCalledWith('error')
            expect(mockSideEffectResultCounter.inc).toHaveBeenCalledTimes(2)
        })

        it('should track mixed success and failure side effects when await is true', async () => {
            const successfulSideEffect = Promise.resolve('success')
            const failingSideEffect = Promise.reject(new Error('fail'))

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [
                createContext(ok({ message }), { message, sideEffects: [successfulSideEffect, failingSideEffect] }),
            ]

            pipeline.feed(batchWithSideEffects)
            await pipeline.next()

            expect(mockSideEffectResultCounter.labels).toHaveBeenCalledWith('ok')
            expect(mockSideEffectResultCounter.labels).toHaveBeenCalledWith('error')
            expect(mockSideEffectResultCounter.inc).toHaveBeenCalledTimes(2)
        })

        it('should not track metrics when await is false', async () => {
            const sideEffect = Promise.resolve('success')

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: false }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [createContext(ok({ message }), { message, sideEffects: [sideEffect] })]

            pipeline.feed(batchWithSideEffects)
            await pipeline.next()

            expect(mockSideEffectResultCounter.labels).not.toHaveBeenCalled()
            expect(mockSideEffectResultCounter.inc).not.toHaveBeenCalled()
            expect(mockPromiseScheduler.schedule).toHaveBeenCalledWith(sideEffect)
        })

        it('should not track metrics when there are no side effects', async () => {
            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithNoSideEffects = [createContext(ok({ message }), { message, sideEffects: [] })]

            pipeline.feed(batchWithNoSideEffects)
            await pipeline.next()

            expect(mockSideEffectResultCounter.labels).not.toHaveBeenCalled()
            expect(mockSideEffectResultCounter.inc).not.toHaveBeenCalled()
        })

        it('should track metrics across multiple results when await is true', async () => {
            const successSideEffect = Promise.resolve('success')
            const failSideEffect = Promise.reject(new Error('fail'))
            const message2 = { ...message, offset: 2 } as Message

            const subPipeline = createNewBatchPipeline<{ message: Message }>().build()
            const config: SideEffectHandlingConfig = { await: true }
            const pipeline = new SideEffectHandlingPipeline(subPipeline, mockPromiseScheduler, config)

            const batchWithSideEffects = [
                createContext(ok({ message }), { message, sideEffects: [successSideEffect] }),
                createContext(ok({ message: message2 }), { message: message2, sideEffects: [failSideEffect] }),
            ]

            pipeline.feed(batchWithSideEffects)
            await pipeline.next()

            expect(mockSideEffectResultCounter.labels).toHaveBeenCalledWith('ok')
            expect(mockSideEffectResultCounter.labels).toHaveBeenCalledWith('error')
            expect(mockSideEffectResultCounter.inc).toHaveBeenCalledTimes(2)
        })
    })
})
