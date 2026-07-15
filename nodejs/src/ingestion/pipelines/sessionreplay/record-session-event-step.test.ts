import { DateTime } from 'luxon'

import { PipelineResultType } from '~/ingestion/framework/results'
import { extractConsoleLogs } from '~/ingestion/pipelines/sessionreplay/extract-console-logs-step'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { serializeSessionData } from '~/ingestion/pipelines/sessionreplay/serialize-session-step'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { RecordSessionEventStepInput, createRecordSessionEventStep } from './record-session-event-step'

jest.mock('~/ingestion/pipelines/sessionreplay/metrics', () => ({
    SessionRecordingIngesterMetrics: {
        resetSessionsRevoked: jest.fn(),
        observeSessionInfo: jest.fn(),
    },
}))

describe('createRecordSessionEventStep', () => {
    let mockBatchRecorder: jest.Mocked<SessionBatchRecorder>

    const defaultTeam: TeamForReplay = {
        teamId: 1,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn: true,
        firstPartyHosts: [],
    }

    const createParsedMessage = (overrides: Partial<ParsedMessageData> = {}): ParsedMessageData => ({
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
        ...overrides,
    })

    // Builds the step's input the way the serialize step does in the pipeline.
    const createInput = (
        overrides: Partial<ParsedMessageData> = {},
        team: TeamForReplay = defaultTeam
    ): RecordSessionEventStepInput => {
        const parsedMessage = createParsedMessage(overrides)
        return {
            session: {
                teamId: team.teamId,
                sessionId: parsedMessage.session_id,
                partition: parsedMessage.metadata.partition,
                retentionPeriod: '30d',
                sessionKey: createMockSessionKey(),
            },
            data: serializeSessionData(parsedMessage),
            logs: extractConsoleLogs({ team, message: parsedMessage }),
            parsedMessage,
            // The recorder is tagged onto the element by the pipeline's beforeBatch.
            sessionBatchRecorder: mockBatchRecorder,
        }
    }

    beforeEach(() => {
        jest.clearAllMocks()

        mockBatchRecorder = {
            recordSessionData: jest.fn().mockReturnValue({ accepted: true, bytesWritten: 100 }),
            recordSessionLogs: jest.fn().mockResolvedValue(undefined),
            recordSessionFeatures: jest.fn(),
        } as unknown as jest.Mocked<SessionBatchRecorder>
    })

    it('should record the serialized data, logs, and features to the recorder on the element', async () => {
        const step = createRecordSessionEventStep({
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput()
        await step(input)

        expect(mockBatchRecorder.recordSessionData).toHaveBeenCalledTimes(1)
        expect(mockBatchRecorder.recordSessionData).toHaveBeenCalledWith(input.session, input.data)
        expect(mockBatchRecorder.recordSessionLogs).toHaveBeenCalledWith(input.session, input.logs)
        expect(mockBatchRecorder.recordSessionFeatures).toHaveBeenCalledWith(input.session, input.parsedMessage)
    })

    it('should not record logs or features when the recorder rejects the message', async () => {
        mockBatchRecorder.recordSessionData.mockReturnValue({ accepted: false, bytesWritten: 0 })
        const step = createRecordSessionEventStep({
            isDebugLoggingEnabled: () => false,
        })

        await step(createInput())

        expect(mockBatchRecorder.recordSessionLogs).not.toHaveBeenCalled()
        expect(mockBatchRecorder.recordSessionFeatures).not.toHaveBeenCalled()
    })

    it('should return ok result with input preserved', async () => {
        const step = createRecordSessionEventStep({
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput()
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toBe(input)
            expect(result.value.session).toBe(input.session)
            expect(result.value.parsedMessage).toBe(input.parsedMessage)
        }
    })

    it('should reset sessions revoked metric', async () => {
        const step = createRecordSessionEventStep({
            isDebugLoggingEnabled: () => false,
        })

        await step(createInput())

        expect(SessionRecordingIngesterMetrics.resetSessionsRevoked).toHaveBeenCalledTimes(1)
    })

    it('should observe session info metric', async () => {
        const step = createRecordSessionEventStep({
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput({ metadata: { partition: 0, topic: 'test', offset: 1, timestamp: 0, rawSize: 250 } })
        await step(input)

        expect(SessionRecordingIngesterMetrics.observeSessionInfo).toHaveBeenCalledWith(250)
    })

    it('should preserve additional input properties', async () => {
        const step = createRecordSessionEventStep<RecordSessionEventStepInput & { extraProperty: string }>({
            isDebugLoggingEnabled: () => false,
        })

        const input = {
            ...createInput(),
            extraProperty: 'should be preserved',
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.extraProperty).toBe('should be preserved')
        }
    })
})
