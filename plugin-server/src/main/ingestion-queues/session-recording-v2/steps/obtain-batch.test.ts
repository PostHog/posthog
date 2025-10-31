import { isOkResult, ok } from '../../../../ingestion/pipelines/results'
import { SessionBatchManager } from '../sessions/session-batch-manager'
import { SessionBatchRecorder } from '../sessions/session-batch-recorder'
import { TeamForReplay } from '../teams/types'
import { createTestMessage } from '../test-helpers'
import { createObtainBatchStep } from './obtain-batch'

describe('obtain-batch', () => {
    const mockBatchRecorder = {} as SessionBatchRecorder

    const mockSessionBatchManager = {
        getCurrentBatch: jest.fn(),
    } as unknown as SessionBatchManager

    beforeEach(() => {
        jest.clearAllMocks()
        ;(mockSessionBatchManager.getCurrentBatch as jest.Mock).mockReturnValue(mockBatchRecorder)
    })

    const createInput = (teamId: number) => {
        const message = createTestMessage()
        const headers = {
            token: 'test-token',
            distinct_id: 'user-123',
            force_disable_person_processing: false,
        }
        const parsedMessage = {
            metadata: {
                partition: 0,
                topic: 'test-topic',
                rawSize: 1024,
                offset: 0,
                timestamp: 1672527600000,
            },
            headers: [],
            distinct_id: 'user-123',
            session_id: 'session-123',
            eventsByWindowId: {},
            eventsRange: { start: null as any, end: null as any },
            snapshot_source: null,
            snapshot_library: null,
        }
        const team: TeamForReplay = {
            teamId,
            consoleLogIngestionEnabled: true,
        }

        return { message, headers, parsedMessage, team }
    }

    it('should attach batch recorder to single message', async () => {
        const step = createObtainBatchStep(mockSessionBatchManager)
        const input = createInput(123)

        const results = await step([input])

        expect(results).toHaveLength(1)
        expect(isOkResult(results[0])).toBe(true)
        expect(results[0]).toEqual(
            ok({
                ...input,
                batchRecorder: mockBatchRecorder,
            })
        )
        expect(mockSessionBatchManager.getCurrentBatch).toHaveBeenCalledTimes(1)
    })

    it('should attach same batch recorder to multiple messages', async () => {
        const step = createObtainBatchStep(mockSessionBatchManager)
        const input1 = createInput(123)
        const input2 = createInput(456)
        const input3 = createInput(789)

        const results = await step([input1, input2, input3])

        expect(results).toHaveLength(3)
        expect(isOkResult(results[0])).toBe(true)
        expect(isOkResult(results[1])).toBe(true)
        expect(isOkResult(results[2])).toBe(true)

        // All messages should have the same batch recorder
        expect(results[0]).toEqual(ok({ ...input1, batchRecorder: mockBatchRecorder }))
        expect(results[1]).toEqual(ok({ ...input2, batchRecorder: mockBatchRecorder }))
        expect(results[2]).toEqual(ok({ ...input3, batchRecorder: mockBatchRecorder }))

        // getCurrentBatch should only be called once per batch
        expect(mockSessionBatchManager.getCurrentBatch).toHaveBeenCalledTimes(1)
    })

    it('should handle empty batch', async () => {
        const step = createObtainBatchStep(mockSessionBatchManager)

        const results = await step([])

        expect(results).toHaveLength(0)
        expect(mockSessionBatchManager.getCurrentBatch).toHaveBeenCalledTimes(1)
    })

    it('should preserve all input fields', async () => {
        const step = createObtainBatchStep(mockSessionBatchManager)
        const input = createInput(123)

        const results = await step([input])

        expect(isOkResult(results[0])).toBe(true)
        if (isOkResult(results[0])) {
            expect(results[0].value.message).toEqual(input.message)
            expect(results[0].value.headers).toEqual(input.headers)
            expect(results[0].value.parsedMessage).toEqual(input.parsedMessage)
            expect(results[0].value.team).toEqual(input.team)
            expect(results[0].value.batchRecorder).toBe(mockBatchRecorder)
        }
    })
})
