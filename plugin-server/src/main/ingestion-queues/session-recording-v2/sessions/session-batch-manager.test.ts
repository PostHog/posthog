import { KafkaOffsetManager } from '../kafka/offset-manager'
import { SessionBatchManager } from './session-batch-manager'
import { SessionBatchRecorder } from './session-batch-recorder'

jest.setTimeout(1000)
jest.mock('./session-batch-recorder')

describe('SessionBatchManager', () => {
    let manager: SessionBatchManager
    let executionOrder: number[]
    let currentBatch: jest.Mocked<SessionBatchRecorder>
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>

    const createMockBatch = (): jest.Mocked<SessionBatchRecorder> =>
        ({
            record: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
            get size() {
                return 0
            },
            discardPartition: jest.fn(),
        } as unknown as jest.Mocked<SessionBatchRecorder>)

    beforeEach(() => {
        jest.mocked(SessionBatchRecorder).mockImplementation(() => {
            currentBatch = createMockBatch()
            return currentBatch
        })

        mockOffsetManager = {
            commit: jest.fn().mockResolvedValue(undefined),
            trackOffset: jest.fn(),
            discardPartition: jest.fn(),
        } as unknown as jest.Mocked<KafkaOffsetManager>

        manager = new SessionBatchManager({
            maxBatchSizeBytes: 100,
            maxBatchAgeMs: 1000,
            offsetManager: mockOffsetManager,
        })
        executionOrder = []
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    const waitForNextTick = () => new Promise((resolve) => process.nextTick(resolve))

    const waitFor = async (condition: () => boolean) => {
        while (!condition()) {
            await waitForNextTick()
        }
    }

    const waitForValue = async (array: number[], value: number) => {
        await waitFor(() => array.includes(value))
    }

    it('should execute callbacks sequentially', async () => {
        const promise1 = manager.withBatch(async () => {
            executionOrder.push(1)
            await waitForValue(executionOrder, 1)
            executionOrder.push(2)
        })

        const promise2 = manager.withBatch(async () => {
            executionOrder.push(3)
            await waitForValue(executionOrder, 3)
            executionOrder.push(4)
        })

        const promise3 = manager.withBatch(async () => {
            executionOrder.push(5)
            executionOrder.push(6)
            return Promise.resolve()
        })

        await Promise.all([promise1, promise2, promise3])

        expect(executionOrder).toEqual([1, 2, 3, 4, 5, 6])
    })

    it('should handle errors without breaking the queue', async () => {
        const errorSpy = jest.fn()

        const promise1 = manager
            .withBatch(async () => {
                executionOrder.push(1)
                throw new Error('test error')
                return Promise.resolve()
            })
            .catch(errorSpy)

        const promise2 = manager.withBatch(async () => {
            executionOrder.push(2)
            return Promise.resolve()
        })

        await Promise.all([promise1, promise2])

        expect(executionOrder).toEqual([1, 2])
        expect(errorSpy).toHaveBeenCalled()
    })

    it('should maintain order even with immediate callbacks', async () => {
        const results: number[] = []
        const promises: Promise<void>[] = []

        for (let i = 0; i < 10; i++) {
            promises.push(
                manager.withBatch(async () => {
                    results.push(i)
                    return Promise.resolve()
                })
            )
        }

        await Promise.all(promises)

        expect(results).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    })

    it('should process new callbacks added during execution', async () => {
        const results: number[] = []
        let nestedPromise: Promise<void> | null = null
        let promise2: Promise<void> | null = null
        const promise1 = manager.withBatch(async () => {
            results.push(1)
            // Add a new callback while this one is executing
            nestedPromise = manager.withBatch(async () => {
                await waitFor(() => promise2 !== null)
                results.push(2)
                return Promise.resolve()
            })
            return Promise.resolve()
        })

        await waitFor(() => nestedPromise !== null)
        promise2 = manager.withBatch(async () => {
            results.push(3)
            return Promise.resolve()
        })

        await Promise.all([promise1, promise2, nestedPromise!])

        expect(results).toEqual([1, 2, 3])
    })

    it('should create new batch on flush', async () => {
        let firstBatch: SessionBatchRecorder | null = null

        await manager.withBatch(async (batch) => {
            firstBatch = batch
            return Promise.resolve()
        })

        await manager.flush()

        await manager.withBatch(async (batch) => {
            expect(batch).not.toBe(firstBatch)
            return Promise.resolve()
        })
    })

    it('should create new batch with correct params on flush', async () => {
        let firstBatch: SessionBatchRecorder | null = null
        await manager.withBatch(async (batch) => {
            firstBatch = batch
            expect(batch).toBeDefined()
            return Promise.resolve()
        })

        await manager.flush()

        expect(firstBatch!.flush).toHaveBeenCalled()
        expect(SessionBatchRecorder).toHaveBeenCalledWith(mockOffsetManager)

        await manager.withBatch(async (batch) => {
            expect(batch).not.toBe(firstBatch)
            expect(batch.size).toBe(0)
            return Promise.resolve()
        })
    })

    describe('size-based flushing', () => {
        it('should indicate flush needed when buffer is full', () => {
            jest.spyOn(currentBatch, 'size', 'get').mockReturnValue(150)
            expect(manager.shouldFlush()).toBe(true)
        })

        it('should not indicate flush needed when buffer is under limit', () => {
            jest.spyOn(currentBatch, 'size', 'get').mockReturnValue(50)
            expect(manager.shouldFlush()).toBe(false)
        })
    })

    describe('time-based flushing', () => {
        beforeEach(() => {
            jest.useFakeTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('should not indicate flush needed when buffer is under limit and timeout not reached', () => {
            jest.spyOn(currentBatch, 'size', 'get').mockReturnValue(50)
            jest.advanceTimersByTime(500) // Advance time by 500ms (less than timeout)
            expect(manager.shouldFlush()).toBe(false)
        })

        it('should indicate flush needed when timeout is reached', () => {
            jest.spyOn(currentBatch, 'size', 'get').mockReturnValue(50)
            jest.advanceTimersByTime(1500) // Advance time by 1.5s (more than timeout)
            expect(manager.shouldFlush()).toBe(true)
        })

        it('should indicate flush needed when buffer is full', () => {
            jest.spyOn(currentBatch, 'size', 'get').mockReturnValue(150)
            expect(manager.shouldFlush()).toBe(true)
        })

        it('should not indicate flush needed immediately after flushing', async () => {
            let firstBatch: SessionBatchRecorder | null = null
            const promise1 = manager.withBatch(async (batch) => {
                firstBatch = batch
                jest.spyOn(batch, 'size', 'get').mockReturnValue(50)
                return Promise.resolve()
            })

            // First flush due to timeout
            jest.advanceTimersByTime(1500)
            await promise1
            expect(manager.shouldFlush()).toBe(true)

            const firstFlushPromise = manager.flush()
            jest.runAllTimers()
            await firstFlushPromise
            expect(firstBatch!.flush).toHaveBeenCalled()

            const promise2 = manager.withBatch(async (batch) => {
                expect(batch).not.toBe(firstBatch)
                expect(manager.shouldFlush()).toBe(false)
                return Promise.resolve()
            })
            jest.runAllTimers()
            await promise2
        })
    })

    it('should execute callbacks sequentially including flushes', async () => {
        let firstBatch: SessionBatchRecorder | null = null
        const promise1 = await manager.withBatch(async (batch) => {
            firstBatch = batch
            executionOrder.push(1)
            return Promise.resolve()
        })

        const flushPromise = manager.flush()

        const promise2 = await manager.withBatch(async (batch) => {
            expect(batch).not.toBe(firstBatch)
            executionOrder.push(2)
            return Promise.resolve()
        })

        await Promise.all([promise1, flushPromise, promise2])

        expect(executionOrder).toEqual([1, 2])
        expect(firstBatch!.flush).toHaveBeenCalled()
    })

    describe('partition handling', () => {
        it('should discard partitions on new batch after flush', async () => {
            let firstBatch: SessionBatchRecorder | null = null
            let secondBatch: SessionBatchRecorder | null = null

            await manager.withBatch(async (batch) => {
                firstBatch = batch
                await Promise.resolve()
            })

            await manager.flush()

            await manager.withBatch(async (batch) => {
                secondBatch = batch
                expect(batch).not.toBe(firstBatch)
                await Promise.resolve()
            })

            await manager.discardPartitions([1, 2])

            expect(firstBatch!.discardPartition).not.toHaveBeenCalled()
            expect(secondBatch!.discardPartition).toHaveBeenCalledWith(1)
            expect(secondBatch!.discardPartition).toHaveBeenCalledWith(2)
        })

        it('should discard multiple partitions on current batch', async () => {
            let currentBatch: SessionBatchRecorder | null = null
            await manager.withBatch(async (batch) => {
                currentBatch = batch
                await Promise.resolve()
            })

            await manager.discardPartitions([1, 2])
            expect(currentBatch!.discardPartition).toHaveBeenCalledWith(1)
            expect(currentBatch!.discardPartition).toHaveBeenCalledWith(2)
            expect(currentBatch!.discardPartition).toHaveBeenCalledTimes(2)
        })

        it('should maintain operation order when discarding partitions', async () => {
            const executionOrder: number[] = []
            let currentBatch: SessionBatchRecorder | null = null

            // Start a long-running batch operation
            const batchPromise = manager.withBatch(async (batch) => {
                currentBatch = batch
                await new Promise((resolve) => setTimeout(resolve, 100))
                executionOrder.push(1)
            })

            // Queue up a partition discard
            const discardPromise = manager.discardPartitions([1]).then(() => {
                executionOrder.push(2)
            })

            // Wait for both operations to complete
            await Promise.all([batchPromise, discardPromise])

            // Verify operations happened in the correct order
            expect(executionOrder).toEqual([1, 2])
            expect(currentBatch!.discardPartition).toHaveBeenCalledWith(1)
        })

        it('should handle empty partition array', async () => {
            let currentBatch: SessionBatchRecorder | null = null
            await manager.withBatch(async (batch) => {
                currentBatch = batch
                await Promise.resolve()
            })

            await manager.discardPartitions([])
            expect(currentBatch!.discardPartition).not.toHaveBeenCalled()
        })
    })
})
