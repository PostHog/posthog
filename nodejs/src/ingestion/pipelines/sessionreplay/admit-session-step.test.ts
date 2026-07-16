import { DateTime } from 'luxon'

import { PipelineResultType } from '~/ingestion/framework/results'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'

import { AdmitSessionStepInput, createAdmitSessionStep } from './admit-session-step'

jest.mock('~/ingestion/pipelines/sessionreplay/metrics', () => ({
    SessionRecordingIngesterMetrics: {
        resetSessionsRevoked: jest.fn(),
        observeSessionInfo: jest.fn(),
    },
}))

describe('createAdmitSessionStep', () => {
    let mockBatchRecorder: jest.Mocked<SessionBatchRecorder>

    const createParsedMessage = (): ParsedMessageData => ({
        metadata: {
            partition: 0,
            topic: 'test-topic',
            offset: 1,
            timestamp: 1234567890,
            rawSize: 100,
        },
        distinct_id: 'user-123',
        session_id: 'session-456',
        token: 'test-token',
        eventsByWindowId: { window1: [] },
        eventsRange: { start: DateTime.fromMillis(0), end: DateTime.fromMillis(0) },
        snapshot_source: null,
        snapshot_library: null,
    })

    // Builds the step's input in the shape the extract steps produce. The step only reads the
    // session, the event count, and message metadata — the rest passes through untouched.
    const createInput = (): AdmitSessionStepInput => {
        const parsedMessage = createParsedMessage()
        const chunk = Buffer.from(JSON.stringify(['window1', { type: 3, timestamp: 1000 }]) + '\n')
        return {
            session: {
                teamId: 1,
                sessionId: parsedMessage.session_id,
                partition: parsedMessage.metadata.partition,
                retentionPeriod: '30d',
                sessionKey: createMockSessionKey(),
            },
            data: {
                chunks: [chunk],
                rawBytes: chunk.length,
                eventCount: 7,
                segmentationEvents: [],
                urls: [],
                clickCount: 0,
                keypressCount: 0,
                mouseActivityCount: 0,
                eventsRange: parsedMessage.eventsRange,
                distinctId: parsedMessage.distinct_id,
                snapshotSource: 'web',
                snapshotLibrary: null,
            },
            parsedMessage,
            // The recorder is tagged onto the element by the pipeline's beforeBatch.
            sessionBatchRecorder: mockBatchRecorder,
        }
    }

    beforeEach(() => {
        jest.clearAllMocks()

        mockBatchRecorder = {
            admit: jest.fn().mockReturnValue('admitted'),
        } as unknown as jest.Mocked<SessionBatchRecorder>
    })

    it('should admit the message with its event count and pass the input through', async () => {
        const step = createAdmitSessionStep({
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput()
        const result = await step(input)

        expect(mockBatchRecorder.admit).toHaveBeenCalledWith(input.session, 7)
        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toBe(input)
        }
    })

    it('should drop a refused message with the verdict as the reason', async () => {
        mockBatchRecorder.admit.mockReturnValue('session_rate_limited')
        const step = createAdmitSessionStep({
            isDebugLoggingEnabled: () => false,
        })

        const result = await step(createInput())

        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.reason).toBe('session_rate_limited')
        }
    })

    it('should reset sessions revoked metric', async () => {
        const step = createAdmitSessionStep({
            isDebugLoggingEnabled: () => false,
        })

        await step(createInput())

        expect(SessionRecordingIngesterMetrics.resetSessionsRevoked).toHaveBeenCalledTimes(1)
    })

    it('should observe session info metric', async () => {
        const step = createAdmitSessionStep({
            isDebugLoggingEnabled: () => false,
        })

        await step(createInput())

        expect(SessionRecordingIngesterMetrics.observeSessionInfo).toHaveBeenCalledWith(100)
    })
})
