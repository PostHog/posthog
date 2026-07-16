import { DateTime } from 'luxon'

import { PipelineResultType } from '~/ingestion/framework/results'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
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

    // Builds the step's input in the shape the extract steps produce. The record step passes the
    // extracted data through untouched, so its content doesn't matter here.
    const createInput = (
        overrides: Partial<ParsedMessageData> = {},
        team: TeamForReplay = defaultTeam
    ): RecordSessionEventStepInput => {
        const parsedMessage = createParsedMessage(overrides)
        const chunk = Buffer.from(JSON.stringify(['window1', { type: 3, timestamp: 1000 }]) + '\n')
        return {
            session: {
                teamId: team.teamId,
                sessionId: parsedMessage.session_id,
                partition: parsedMessage.metadata.partition,
                retentionPeriod: '30d',
                sessionKey: createMockSessionKey(),
            },
            data: {
                chunks: [chunk],
                rawBytes: chunk.length,
                eventCount: 1,
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
            logs: { consoleLogCount: 0, consoleWarnCount: 0, consoleErrorCount: 0, entries: [] },
            parsedMessage,
            // The recorder is tagged onto the element by the pipeline's beforeBatch.
            sessionBatchRecorder: mockBatchRecorder,
        }
    }

    beforeEach(() => {
        jest.clearAllMocks()

        mockBatchRecorder = {
            record: jest.fn().mockResolvedValue({ accepted: true, bytesWritten: 100 }),
        } as unknown as jest.Mocked<SessionBatchRecorder>
    })

    it('should record the extracted data, logs, and parsed message to the recorder on the element', async () => {
        const step = createRecordSessionEventStep({
            isDebugLoggingEnabled: () => false,
        })

        const input = createInput()
        await step(input)

        expect(mockBatchRecorder.record).toHaveBeenCalledTimes(1)
        expect(mockBatchRecorder.record).toHaveBeenCalledWith(
            input.session,
            input.data,
            input.logs,
            input.parsedMessage
        )
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
