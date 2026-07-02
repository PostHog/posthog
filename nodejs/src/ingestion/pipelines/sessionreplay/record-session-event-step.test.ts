import { DateTime } from 'luxon'

import { PipelineResultType } from '~/ingestion/framework/results'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { SessionBatchManager } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-manager'
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
    let mockSessionBatchManager: jest.Mocked<SessionBatchManager>
    let mockBatchRecorder: jest.Mocked<SessionBatchRecorder>

    const defaultTeam: TeamForReplay = {
        teamId: 1,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn: true,
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

    const createInput = (
        overrides: Partial<ParsedMessageData> = {},
        team: TeamForReplay = defaultTeam
    ): RecordSessionEventStepInput => ({
        team,
        parsedMessage: createParsedMessage(overrides),
        retentionPeriod: '30d',
        sessionKey: createMockSessionKey(),
    })

    beforeEach(() => {
        jest.clearAllMocks()

        mockBatchRecorder = {
            record: jest.fn().mockResolvedValue(100),
        } as unknown as jest.Mocked<SessionBatchRecorder>

        mockSessionBatchManager = {
            getCurrentBatch: jest.fn().mockReturnValue(mockBatchRecorder),
        } as unknown as jest.Mocked<SessionBatchManager>
    })

    it('should record message to session batch', async () => {
        const step = createRecordSessionEventStep({
            sessionBatchManager: mockSessionBatchManager,
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput()
        await step(input)

        expect(mockSessionBatchManager.getCurrentBatch).toHaveBeenCalledTimes(1)
        expect(mockBatchRecorder.record).toHaveBeenCalledTimes(1)
        expect(mockBatchRecorder.record).toHaveBeenCalledWith(
            {
                team: defaultTeam,
                message: input.parsedMessage,
            },
            '30d',
            input.sessionKey
        )
    })

    it('should return ok result with input preserved', async () => {
        const step = createRecordSessionEventStep({
            sessionBatchManager: mockSessionBatchManager,
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput()
        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value).toBe(input)
            expect(result.value.team).toBe(defaultTeam)
            expect(result.value.parsedMessage).toBe(input.parsedMessage)
        }
    })

    it('should reset sessions revoked metric', async () => {
        const step = createRecordSessionEventStep({
            sessionBatchManager: mockSessionBatchManager,
            isDebugLoggingEnabled: () => false,
        })

        await step(createInput())

        expect(SessionRecordingIngesterMetrics.resetSessionsRevoked).toHaveBeenCalledTimes(1)
    })

    it('should observe session info metric', async () => {
        const step = createRecordSessionEventStep({
            sessionBatchManager: mockSessionBatchManager,
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput({ metadata: { partition: 0, topic: 'test', offset: 1, timestamp: 0, rawSize: 250 } })
        await step(input)

        expect(SessionRecordingIngesterMetrics.observeSessionInfo).toHaveBeenCalledWith(250)
    })

    it('should preserve additional input properties', async () => {
        const step = createRecordSessionEventStep<RecordSessionEventStepInput & { extraProperty: string }>({
            sessionBatchManager: mockSessionBatchManager,
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
