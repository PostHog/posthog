import { ok } from '../../../../ingestion/pipelines/results'
import { SessionBatchManager } from '../sessions/session-batch-manager'
import { createMaybeFlushBatchStep } from './maybe-flush-batch'

describe('maybe-flush-batch', () => {
    const mockSessionBatchManager = {
        shouldFlush: jest.fn(),
        flush: jest.fn(),
    } as unknown as SessionBatchManager

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('should flush when shouldFlush returns true and pass through input', async () => {
        ;(mockSessionBatchManager.shouldFlush as jest.Mock).mockReturnValue(true)
        ;(mockSessionBatchManager.flush as jest.Mock).mockResolvedValue(undefined)

        const input = [{ data: 'test1' }, { data: 'test2' }]
        const step = createMaybeFlushBatchStep(mockSessionBatchManager)
        const result = await step(input)

        expect(mockSessionBatchManager.shouldFlush).toHaveBeenCalled()
        expect(mockSessionBatchManager.flush).toHaveBeenCalled()
        expect(result).toEqual([ok({ data: 'test1' }), ok({ data: 'test2' })])
    })

    it('should not flush when shouldFlush returns false but still pass through input', async () => {
        ;(mockSessionBatchManager.shouldFlush as jest.Mock).mockReturnValue(false)

        const input = [{ data: 'test' }]
        const step = createMaybeFlushBatchStep(mockSessionBatchManager)
        const result = await step(input)

        expect(mockSessionBatchManager.shouldFlush).toHaveBeenCalled()
        expect(mockSessionBatchManager.flush).not.toHaveBeenCalled()
        expect(result).toEqual([ok({ data: 'test' })])
    })

    it('should pass through empty batch', async () => {
        ;(mockSessionBatchManager.shouldFlush as jest.Mock).mockReturnValue(false)

        const step = createMaybeFlushBatchStep(mockSessionBatchManager)
        const result = await step([])

        expect(result).toEqual([])
    })

    it('should handle flush errors', async () => {
        const flushError = new Error('Flush failed')
        ;(mockSessionBatchManager.shouldFlush as jest.Mock).mockReturnValue(true)
        ;(mockSessionBatchManager.flush as jest.Mock).mockRejectedValue(flushError)

        const step = createMaybeFlushBatchStep(mockSessionBatchManager)

        await expect(step([])).rejects.toThrow('Flush failed')
        expect(mockSessionBatchManager.shouldFlush).toHaveBeenCalled()
        expect(mockSessionBatchManager.flush).toHaveBeenCalled()
    })
})
