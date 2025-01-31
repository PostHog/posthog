import { KafkaOffsetManager } from '../kafka/offset-manager'
import { SessionBatchFileWriter } from './session-batch-file-writer'
import { SessionBatchManager } from './session-batch-manager'
import { SessionBatchRecorder } from './session-batch-recorder'

jest.setTimeout(1000)
jest.mock('./session-batch-recorder')

describe('SessionBatchManager', () => {
    let manager: SessionBatchManager
    let currentBatch: jest.Mocked<SessionBatchRecorder>
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>
    let mockWriter: jest.Mocked<SessionBatchFileWriter>

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

        mockWriter = {
            open: jest.fn(),
        } as unknown as jest.Mocked<SessionBatchFileWriter>

        manager = new SessionBatchManager({
            maxBatchSizeBytes: 100,
            maxBatchAgeMs: 1000,
            offsetManager: mockOffsetManager,
            writer: mockWriter,
        })
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    it('should create new batch with correct params on flush', async () => {
        const firstBatch = manager.getCurrentBatch()
        await manager.flush()

        expect(firstBatch.flush).toHaveBeenCalled()
        expect(SessionBatchRecorder).toHaveBeenCalledWith(mockOffsetManager, mockWriter)

        const secondBatch = manager.getCurrentBatch()
        expect(secondBatch).not.toBe(firstBatch)
        expect(secondBatch.size).toBe(0)
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
            jest.advanceTimersByTime(500)
            expect(manager.shouldFlush()).toBe(false)
        })

        it('should indicate flush needed when timeout is reached', () => {
            jest.spyOn(currentBatch, 'size', 'get').mockReturnValue(50)
            jest.advanceTimersByTime(1500)
            expect(manager.shouldFlush()).toBe(true)
        })

        it('should not indicate flush needed immediately after flushing', async () => {
            jest.spyOn(currentBatch, 'size', 'get').mockReturnValue(50)
            jest.advanceTimersByTime(1500)
            expect(manager.shouldFlush()).toBe(true)

            await manager.flush()
            expect(manager.shouldFlush()).toBe(false)
        })
    })

    describe('partition handling', () => {
        it('should discard partitions on current batch', () => {
            const batch = manager.getCurrentBatch()
            manager.discardPartitions([1, 2])

            expect(batch.discardPartition).toHaveBeenCalledWith(1)
            expect(batch.discardPartition).toHaveBeenCalledWith(2)
            expect(batch.discardPartition).toHaveBeenCalledTimes(2)
        })

        it('should handle empty partition array', () => {
            const batch = manager.getCurrentBatch()
            manager.discardPartitions([])
            expect(batch.discardPartition).not.toHaveBeenCalled()
        })
    })

    describe('constructor', () => {
        it('should create a new batch recorder with the writer', () => {
            expect(SessionBatchRecorder).toHaveBeenCalledWith(mockOffsetManager, mockWriter)
        })
    })
})
