import { ok } from '../../../../ingestion/pipelines/results'
import { SessionRecordingIngesterMetrics } from '../metrics'
import { SessionBatchRecorder } from '../sessions/session-batch-recorder'
import { MessageWithTeam, TeamForReplay } from '../teams/types'
import { createTestMessage } from '../test-helpers'
import { createRecordSessionEventStep } from './record-session-event'

jest.mock('../metrics')
jest.mock('../../../../utils/logger')

describe('record-session-event', () => {
    const mockTeam: TeamForReplay = {
        teamId: 123,
        consoleLogIngestionEnabled: true,
    }

    const mockMessage = createTestMessage()

    const mockParsedMessage = {
        metadata: {
            partition: 1,
            topic: 'test-topic',
            offset: 100,
            timestamp: 1672527600000,
            rawSize: 1024,
        },
        headers: [],
        distinct_id: 'user123',
        session_id: 'session456',
        eventsByWindowId: {},
        eventsRange: { start: null as any, end: null as any },
        snapshot_source: null,
        snapshot_library: null,
    }

    const mockInput = {
        message: mockMessage,
        headers: {
            token: 'test-token',
            distinct_id: 'user123',
            force_disable_person_processing: false,
        },
        parsedMessage: mockParsedMessage,
        team: mockTeam,
        batchRecorder: {} as SessionBatchRecorder,
    }

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('should record message to batch recorder', async () => {
        const mockRecord = jest.fn().mockResolvedValue(undefined)
        const input = {
            ...mockInput,
            batchRecorder: { record: mockRecord } as unknown as SessionBatchRecorder,
        }

        const step = createRecordSessionEventStep(() => false)
        const result = await step(input)

        expect(result).toEqual(ok(undefined))
        expect(mockRecord).toHaveBeenCalledWith({
            team: mockTeam,
            message: mockParsedMessage,
        } as MessageWithTeam)
    })

    it('should reset sessions revoked metric', async () => {
        const mockRecord = jest.fn().mockResolvedValue(undefined)
        const input = {
            ...mockInput,
            batchRecorder: { record: mockRecord } as unknown as SessionBatchRecorder,
        }

        const step = createRecordSessionEventStep(() => false)
        await step(input)

        expect(SessionRecordingIngesterMetrics.resetSessionsRevoked).toHaveBeenCalled()
    })

    it('should observe session info metrics', async () => {
        const mockRecord = jest.fn().mockResolvedValue(undefined)
        const input = {
            ...mockInput,
            batchRecorder: { record: mockRecord } as unknown as SessionBatchRecorder,
        }

        const step = createRecordSessionEventStep(() => false)
        await step(input)

        expect(SessionRecordingIngesterMetrics.observeSessionInfo).toHaveBeenCalledWith(
            mockParsedMessage.metadata.rawSize
        )
    })

    it('should not log debug info when debug logging is disabled', async () => {
        const { logger } = require('../../../../utils/logger')
        const mockRecord = jest.fn().mockResolvedValue(undefined)
        const input = {
            ...mockInput,
            batchRecorder: { record: mockRecord } as unknown as SessionBatchRecorder,
        }

        const step = createRecordSessionEventStep(() => false)
        await step(input)

        expect(logger.debug).not.toHaveBeenCalled()
        expect(logger.info).not.toHaveBeenCalled()
    })

    it('should log debug info when debug logging is enabled for partition', async () => {
        const { logger } = require('../../../../utils/logger')
        const mockRecord = jest.fn().mockResolvedValue(undefined)
        const input = {
            ...mockInput,
            batchRecorder: { record: mockRecord } as unknown as SessionBatchRecorder,
        }

        const step = createRecordSessionEventStep((partition: number) => partition === 1)
        await step(input)

        expect(logger.debug).toHaveBeenCalledWith('🔄', 'processing_session_recording', {
            partition: mockParsedMessage.metadata.partition,
            offset: mockParsedMessage.metadata.offset,
            distinct_id: mockParsedMessage.distinct_id,
            session_id: mockParsedMessage.session_id,
            raw_size: mockParsedMessage.metadata.rawSize,
        })

        expect(logger.info).toHaveBeenCalledWith(
            '🔁',
            '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - consuming event',
            {
                ...mockParsedMessage.metadata,
                team_id: mockTeam.teamId,
                session_id: mockParsedMessage.session_id,
            }
        )
    })

    it('should handle batch recorder errors', async () => {
        const mockError = new Error('Batch recorder failed')
        const mockRecord = jest.fn().mockRejectedValue(mockError)
        const input = {
            ...mockInput,
            batchRecorder: { record: mockRecord } as unknown as SessionBatchRecorder,
        }

        const step = createRecordSessionEventStep(() => false)

        await expect(step(input)).rejects.toThrow('Batch recorder failed')
    })
})
