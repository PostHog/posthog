import { isOkResult } from '~/ingestion/framework/results'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { createRecordMetricsStep } from './session-batch-record-metrics-step'
import { SessionBatchMetrics } from './sessions/metrics'

jest.mock('./sessions/metrics', () => ({
    SessionBatchMetrics: { recordFlushedBatch: jest.fn() },
}))

describe('createRecordMetricsStep', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('records the flushed batch from the threaded block metadata and passes the value through unchanged', async () => {
        const blocks = [
            { sessionId: 's1', eventCount: 2, blockLength: 100 },
            { sessionId: 's2', eventCount: 1, blockLength: 40 },
        ] as unknown as SessionBlockMetadata[]
        const input = { elements: [], batchContext: { batchId: 0 }, blockMetadata: blocks }

        const result = await createRecordMetricsStep()(input)

        expect(SessionBatchMetrics.recordFlushedBatch).toHaveBeenCalledWith(blocks)
        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value).toBe(input)
        }
    })

    it('passes an empty flush through as ok (recordFlushedBatch no-ops on it)', async () => {
        const input = { elements: [], batchContext: { batchId: 0 }, blockMetadata: [] as SessionBlockMetadata[] }

        const result = await createRecordMetricsStep()(input)

        expect(SessionBatchMetrics.recordFlushedBatch).toHaveBeenCalledWith([])
        expect(isOkResult(result)).toBe(true)
    })
})
