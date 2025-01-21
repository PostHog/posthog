import { KafkaOffsetManager } from '../../../../../src/main/ingestion-queues/session-recording-v2/kafka/offset-manager'
import { SessionBatchManager } from '../../../../../src/main/ingestion-queues/session-recording-v2/sessions/session-batch-manager'
import { SessionBatchRecorder } from '../../../../../src/main/ingestion-queues/session-recording-v2/sessions/session-batch-recorder'

const createMockBatch = (): jest.Mocked<SessionBatchRecorder> => {
    return {
        record: jest.fn(),
        flush: jest.fn().mockResolvedValue(undefined),
        get size() {
            return 0
        },
    } as unknown as jest.Mocked<SessionBatchRecorder>
}

describe('SessionBatchManager', () => {
    let manager: SessionBatchManager
    let executionOrder: number[]
    let createBatchMock: jest.Mock<SessionBatchRecorder>
    let currentBatch: jest.Mocked<SessionBatchRecorder>
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>

    beforeEach(() => {
        currentBatch = createMockBatch()
        createBatchMock = jest.fn().mockImplementation(() => {
            currentBatch = createMockBatch()
            return currentBatch
        })

        mockOffsetManager = {
            wrapBatch: jest.fn().mockImplementation((batch) => batch),
            commit: jest.fn().mockResolvedValue(undefined),
            trackOffset: jest.fn(),
        } as unknown as jest.Mocked<KafkaOffsetManager>

        manager = new SessionBatchManager({
            maxBatchSizeBytes: 100,
            createBatch: createBatchMock,
            offsetManager: mockOffsetManager,
        })
        executionOrder = []
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

        // Should execute in order despite different delays
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

        // Queue up 10 immediate callbacks
        for (let i = 0; i < 10; i++) {
            promises.push(
                manager.withBatch(async () => {
                    results.push(i)
                    return Promise.resolve()
                })
            )
        }

        await Promise.all(promises)

        // Should execute in order 0-9
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

    it('should create new batch and commit offsets on flush', async () => {
        const firstBatch = currentBatch

        await manager.flush()

        expect(firstBatch.flush).toHaveBeenCalled()
        expect(mockOffsetManager.commit).toHaveBeenCalled()
        expect(createBatchMock).toHaveBeenCalledTimes(2)
    })

    it('should flush and commit when buffer is full', async () => {
        const firstBatch = currentBatch
        jest.spyOn(firstBatch, 'size', 'get').mockReturnValue(150)

        await manager.flushIfFull()

        expect(firstBatch.flush).toHaveBeenCalled()
        expect(mockOffsetManager.commit).toHaveBeenCalled()
        expect(createBatchMock).toHaveBeenCalledTimes(2)
    })

    it('should not flush when buffer is under limit', async () => {
        const firstBatch = currentBatch
        jest.spyOn(firstBatch, 'size', 'get').mockReturnValue(50)

        await manager.flushIfFull()

        expect(firstBatch.flush).not.toHaveBeenCalled()
        expect(mockOffsetManager.commit).not.toHaveBeenCalled()
        expect(createBatchMock).toHaveBeenCalledTimes(1)
    })

    it('should execute callbacks sequentially including flushes', async () => {
        const firstBatch = currentBatch

        const promise1 = manager.withBatch(async () => {
            executionOrder.push(1)
            return Promise.resolve()
        })

        const flushPromise = manager.flush()

        const promise2 = manager.withBatch(async () => {
            executionOrder.push(2)
            return Promise.resolve()
        })

        await Promise.all([promise1, flushPromise, promise2])

        expect(executionOrder).toEqual([1, 2])
        expect(firstBatch.flush).toHaveBeenCalled()
        expect(mockOffsetManager.commit).toHaveBeenCalled()
    })
})
