import { DateTime } from 'luxon'

import { ParsedMessageData } from '../../session-recording/kafka/types'
import { SessionRecordingIngesterMetrics } from '../../session-recording/metrics'
import { SessionBatchManager } from '../../session-recording/sessions/session-batch-manager'
import { SessionBatchRecorder } from '../../session-recording/sessions/session-batch-recorder'
import { TeamForReplay } from '../../session-recording/teams/types'
import { TopTracker } from '../../session-recording/top-tracker'
import { PipelineResultType } from '../pipelines/results'
import { RecordSessionStepInput, createRecordSessionStep } from './record-session-step'

jest.mock('../../session-recording/metrics', () => ({
    SessionRecordingIngesterMetrics: {
        resetSessionsRevoked: jest.fn(),
        observeSessionInfo: jest.fn(),
    },
}))

describe('createRecordSessionStep', () => {
    let mockSessionBatchManager: jest.Mocked<SessionBatchManager>
    let mockBatchRecorder: jest.Mocked<SessionBatchRecorder>
    let topTracker: TopTracker

    const defaultTeam: TeamForReplay = {
        teamId: 1,
        consoleLogIngestionEnabled: false,
    }

    const createParsedMessage = (overrides: Partial<ParsedMessageData> = {}): ParsedMessageData => ({
        metadata: {
            partition: 0,
            topic: 'test-topic',
            offset: 1,
            timestamp: 1234567890,
            rawSize: 100,
        },
        headers: [],
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
    ): RecordSessionStepInput => ({
        team,
        parsedMessage: createParsedMessage(overrides),
    })

    beforeEach(() => {
        jest.clearAllMocks()

        mockBatchRecorder = {
            record: jest.fn().mockResolvedValue(100),
        } as unknown as jest.Mocked<SessionBatchRecorder>

        mockSessionBatchManager = {
            getCurrentBatch: jest.fn().mockReturnValue(mockBatchRecorder),
        } as unknown as jest.Mocked<SessionBatchManager>

        topTracker = new TopTracker()
    })

    it('should record message to session batch', async () => {
        const step = createRecordSessionStep({
            sessionBatchManager: mockSessionBatchManager,
            topTracker,
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput()
        await step(input)

        expect(mockSessionBatchManager.getCurrentBatch).toHaveBeenCalledTimes(1)
        expect(mockBatchRecorder.record).toHaveBeenCalledTimes(1)
        expect(mockBatchRecorder.record).toHaveBeenCalledWith({
            team: defaultTeam,
            message: input.parsedMessage,
        })
    })

    it('should return ok result with input preserved', async () => {
        const step = createRecordSessionStep({
            sessionBatchManager: mockSessionBatchManager,
            topTracker,
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

    it('should track message size in topTracker', async () => {
        const incrementSpy = jest.spyOn(topTracker, 'increment')

        const step = createRecordSessionStep({
            sessionBatchManager: mockSessionBatchManager,
            topTracker,
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput({ token: 'my-token', session_id: 'my-session' })
        await step(input)

        expect(incrementSpy).toHaveBeenCalledWith(
            'message_size_by_session_id',
            'token:my-token:session_id:my-session',
            100 // rawSize from metadata
        )
    })

    it('should track consume time in topTracker', async () => {
        const incrementSpy = jest.spyOn(topTracker, 'increment')

        const step = createRecordSessionStep({
            sessionBatchManager: mockSessionBatchManager,
            topTracker,
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput({ token: 'my-token', session_id: 'my-session' })
        await step(input)

        // Should have two increment calls: message_size and consume_time
        expect(incrementSpy).toHaveBeenCalledTimes(2)
        expect(incrementSpy).toHaveBeenCalledWith(
            'consume_time_ms_by_session_id',
            'token:my-token:session_id:my-session',
            expect.any(Number)
        )
    })

    it('should use "unknown" token when token is null', async () => {
        const incrementSpy = jest.spyOn(topTracker, 'increment')

        const step = createRecordSessionStep({
            sessionBatchManager: mockSessionBatchManager,
            topTracker,
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput({ token: null, session_id: 'my-session' })
        await step(input)

        expect(incrementSpy).toHaveBeenCalledWith(
            'message_size_by_session_id',
            'token:unknown:session_id:my-session',
            expect.any(Number)
        )
    })

    it('should reset sessions revoked metric', async () => {
        const step = createRecordSessionStep({
            sessionBatchManager: mockSessionBatchManager,
            topTracker,
            isDebugLoggingEnabled: () => false,
        })

        await step(createInput())

        expect(SessionRecordingIngesterMetrics.resetSessionsRevoked).toHaveBeenCalledTimes(1)
    })

    it('should observe session info metric', async () => {
        const step = createRecordSessionStep({
            sessionBatchManager: mockSessionBatchManager,
            topTracker,
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput({ metadata: { partition: 0, topic: 'test', offset: 1, timestamp: 0, rawSize: 250 } })
        await step(input)

        expect(SessionRecordingIngesterMetrics.observeSessionInfo).toHaveBeenCalledWith(250)
    })

    it('should preserve additional input properties', async () => {
        const step = createRecordSessionStep({
            sessionBatchManager: mockSessionBatchManager,
            topTracker,
            isDebugLoggingEnabled: () => false,
        })

        // Input with extra properties
        const input = {
            ...createInput(),
            extraProperty: 'should be preserved',
        }

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect((result.value as any).extraProperty).toBe('should be preserved')
        }
    })
})
