import { isOkResult } from '../../../../ingestion/pipelines/results'
import { SessionRecordingIngesterMetrics } from '../metrics'
import { createTestMessage } from '../test-helpers'
import { createCollectBatchMetricsStep } from './collect-batch-metrics'

jest.mock('../metrics', () => ({
    SessionRecordingIngesterMetrics: {
        observeKafkaBatchSize: jest.fn(),
        observeKafkaBatchSizeKb: jest.fn(),
        incrementMessageReceived: jest.fn(),
    },
}))

describe('collect-batch-metrics', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('should observe batch size metrics', async () => {
        const step = createCollectBatchMetricsStep()
        const batch = [
            { message: createTestMessage({ partition: 0, value: Buffer.alloc(1024), size: 1024 }) },
            { message: createTestMessage({ partition: 0, value: Buffer.alloc(2048), size: 2048 }) },
            { message: createTestMessage({ partition: 1, value: Buffer.alloc(512), size: 512 }) },
        ]

        await step(batch)

        expect(SessionRecordingIngesterMetrics.observeKafkaBatchSize).toHaveBeenCalledWith(3)
        expect(SessionRecordingIngesterMetrics.observeKafkaBatchSizeKb).toHaveBeenCalledWith((1024 + 2048 + 512) / 1024)
    })

    it('should increment per-partition message counts', async () => {
        const step = createCollectBatchMetricsStep()
        const batch = [
            { message: createTestMessage({ partition: 0, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 0, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 0, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 1, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 1, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 2, value: Buffer.alloc(100), size: 100 }) },
        ]

        await step(batch)

        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledTimes(3)
        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledWith(0, 3)
        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledWith(1, 2)
        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledWith(2, 1)
    })

    it('should return ok results for all messages', async () => {
        const step = createCollectBatchMetricsStep()
        const batch = [
            { message: createTestMessage({ partition: 0, value: Buffer.alloc(1024), size: 1024 }) },
            { message: createTestMessage({ partition: 1, value: Buffer.alloc(2048), size: 2048 }) },
        ]

        const results = await step(batch)

        expect(results).toHaveLength(2)
        expect(results.every(isOkResult)).toBe(true)
        expect(results[0]).toMatchObject({
            type: 0, // PipelineResultType.OK
            value: batch[0],
        })
        expect(results[1]).toMatchObject({
            type: 0, // PipelineResultType.OK
            value: batch[1],
        })
    })

    it('should handle empty batch', async () => {
        const step = createCollectBatchMetricsStep()
        const batch: { message: any }[] = []

        const results = await step(batch)

        expect(SessionRecordingIngesterMetrics.observeKafkaBatchSize).toHaveBeenCalledWith(0)
        expect(SessionRecordingIngesterMetrics.observeKafkaBatchSizeKb).toHaveBeenCalledWith(0)
        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).not.toHaveBeenCalled()
        expect(results).toHaveLength(0)
    })

    it('should handle messages with no value', async () => {
        const step = createCollectBatchMetricsStep()
        const batch = [
            {
                message: createTestMessage({ value: null, size: 0 }),
            },
        ]

        const results = await step(batch)

        expect(SessionRecordingIngesterMetrics.observeKafkaBatchSize).toHaveBeenCalledWith(1)
        expect(SessionRecordingIngesterMetrics.observeKafkaBatchSizeKb).toHaveBeenCalledWith(0)
        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledWith(0, 1)
        expect(results).toHaveLength(1)
        expect(isOkResult(results[0])).toBe(true)
    })

    it('should aggregate counts for multiple partitions', async () => {
        const step = createCollectBatchMetricsStep()
        const batch = [
            { message: createTestMessage({ partition: 5, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 10, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 5, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 15, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 10, value: Buffer.alloc(100), size: 100 }) },
            { message: createTestMessage({ partition: 5, value: Buffer.alloc(100), size: 100 }) },
        ]

        await step(batch)

        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledTimes(3)
        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledWith(5, 3)
        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledWith(10, 2)
        expect(SessionRecordingIngesterMetrics.incrementMessageReceived).toHaveBeenCalledWith(15, 1)
    })
})
