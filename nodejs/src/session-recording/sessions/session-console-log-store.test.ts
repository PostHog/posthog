import { LOG_ENTRIES_OUTPUT, LogEntriesOutput } from '../../ingestion/common/outputs'
import { IngestionOutputs } from '../../ingestion/outputs/ingestion-outputs'
import { IngestionOutputMessage } from '../../ingestion/outputs/types'
import { ClickHouseTimestamp } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { ConsoleLogLevel } from '../rrweb-types'
import { SessionBatchMetrics } from './metrics'
import { ConsoleLogEntry, SessionConsoleLogStore } from './session-console-log-store'

// Helper to create a ClickHouseTimestamp for testing
const makeTimestamp = (isoString: string): ClickHouseTimestamp => {
    return isoString as unknown as ClickHouseTimestamp
}

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementConsoleLogsStored: jest.fn(),
    },
}))

type QueueMessagesCall = [LogEntriesOutput, IngestionOutputMessage[]]

const getQueuedMessages = (outputs: jest.Mocked<IngestionOutputs<LogEntriesOutput>>, callIndex: number) => {
    const call = outputs.queueMessages.mock.calls[callIndex] as QueueMessagesCall
    expect(call[0]).toBe(LOG_ENTRIES_OUTPUT)
    return call[1]
}

const parseMessageValue = (msg: IngestionOutputMessage) =>
    parseJSON((msg.value as Buffer).toString()) as ConsoleLogEntry

describe('SessionConsoleLogStore', () => {
    let store: SessionConsoleLogStore
    let mockOutputs: jest.Mocked<IngestionOutputs<LogEntriesOutput>>

    beforeEach(() => {
        jest.clearAllMocks()
        mockOutputs = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<IngestionOutputs<LogEntriesOutput>>

        store = new SessionConsoleLogStore(mockOutputs, { messageLimit: 1000 })
    })

    it('should queue logs to kafka with correct data', async () => {
        const logs: ConsoleLogEntry[] = [
            {
                team_id: 1,
                message: 'Test log message',
                level: ConsoleLogLevel.Info,
                log_source: 'session_replay',
                log_source_id: 'session123',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                batch_id: 'batch123',
            },
            {
                team_id: 2,
                message: 'Test warning message',
                level: ConsoleLogLevel.Warn,
                log_source: 'session_replay',
                log_source_id: 'different456',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:01.500'),
                batch_id: 'batch123',
            },
            {
                team_id: 1,
                message: 'Test error message',
                level: ConsoleLogLevel.Error,
                log_source: 'session_replay',
                log_source_id: 'session123',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:03.000'),
                batch_id: 'batch123',
            },
        ]

        await store.storeSessionConsoleLogs(logs)
        await store.flush()

        expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
        const queuedMessages = getQueuedMessages(mockOutputs, 0)
        const parsedLogs = queuedMessages.map(parseMessageValue)

        expect(parsedLogs).toMatchObject([
            {
                team_id: 1,
                message: 'Test log message',
                level: 'info',
                log_source: 'session_replay',
                log_source_id: 'session123',
                instance_id: null,
                timestamp: '2025-01-01 10:00:00.000',
                batch_id: 'batch123',
            },
            {
                team_id: 2,
                message: 'Test warning message',
                level: 'warn',
                log_source: 'session_replay',
                log_source_id: 'different456',
                instance_id: null,
                timestamp: '2025-01-01 10:00:01.500',
                batch_id: 'batch123',
            },
            {
                team_id: 1,
                message: 'Test error message',
                level: 'error',
                log_source: 'session_replay',
                log_source_id: 'session123',
                instance_id: null,
                timestamp: '2025-01-01 10:00:03.000',
                batch_id: 'batch123',
            },
        ])

        // Verify keys are set to correct session IDs
        expect(queuedMessages[0].key).toEqual('session123')
        expect(queuedMessages[1].key).toEqual('different456')
        expect(queuedMessages[2].key).toEqual('session123')
    })

    it('should handle empty logs array', async () => {
        await store.storeSessionConsoleLogs([])
        await store.flush()
        expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
    })

    it('should handle producer errors', async () => {
        const error = new Error('Kafka producer error')
        mockOutputs.queueMessages.mockRejectedValueOnce(error)

        const logs: ConsoleLogEntry[] = [
            {
                team_id: 1,
                message: 'Test log message',
                level: ConsoleLogLevel.Info,
                log_source: 'session_replay',
                log_source_id: 'session123',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                batch_id: 'batch123',
            },
        ]

        await store.storeSessionConsoleLogs(logs)
        await expect(store.flush()).rejects.toThrow(error)
    })

    it('should preserve batch IDs when storing logs', async () => {
        const logs: ConsoleLogEntry[] = [
            {
                team_id: 1,
                message: 'Test log message 1',
                level: ConsoleLogLevel.Info,
                log_source: 'session_replay',
                log_source_id: 'session1',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                batch_id: 'batch1',
            },
            {
                team_id: 1,
                message: 'Test log message 2',
                level: ConsoleLogLevel.Info,
                log_source: 'session_replay',
                log_source_id: 'session2',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:03.000'),
                batch_id: 'batch2',
            },
        ]

        await store.storeSessionConsoleLogs(logs)
        await store.flush()

        const queuedMessages = getQueuedMessages(mockOutputs, 0)
        const parsedLogs = queuedMessages.map(parseMessageValue)

        expect(parsedLogs[0].batch_id).toBe('batch1')
        expect(parsedLogs[1].batch_id).toBe('batch2')
    })

    describe('metrics', () => {
        it('should increment console logs stored metric', async () => {
            const logs: ConsoleLogEntry[] = [
                {
                    team_id: 1,
                    message: 'Test log message',
                    level: ConsoleLogLevel.Info,
                    log_source: 'session_replay',
                    log_source_id: 'session123',
                    instance_id: null,
                    timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                    batch_id: 'batch123',
                },
                {
                    team_id: 2,
                    message: 'Another log message',
                    level: ConsoleLogLevel.Warn,
                    log_source: 'session_replay',
                    log_source_id: 'session456',
                    instance_id: null,
                    timestamp: makeTimestamp('2025-01-01 10:00:01.000'),
                    batch_id: 'batch123',
                },
            ]

            await store.storeSessionConsoleLogs(logs)
            await store.flush()
            expect(SessionBatchMetrics.incrementConsoleLogsStored).toHaveBeenCalledWith(2)
        })

        it('should not increment metric for empty logs array', async () => {
            await store.storeSessionConsoleLogs([])
            await store.flush()
            expect(SessionBatchMetrics.incrementConsoleLogsStored).not.toHaveBeenCalled()
        })
    })

    describe('message limit and sync behavior', () => {
        beforeEach(() => {
            // Set message limit to 2 to make testing easier
            store = new SessionConsoleLogStore(mockOutputs, { messageLimit: 2 })
        })

        const createTestLog = (id: string): ConsoleLogEntry => ({
            team_id: 1,
            message: `Test message ${id}`,
            level: ConsoleLogLevel.Info,
            log_source: 'session_replay',
            log_source_id: `session${id}`,
            instance_id: null,
            timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
            batch_id: `batch${id}`,
        })

        it('should sync when message limit is reached', async () => {
            const log1 = createTestLog('1')
            const log2 = createTestLog('2')

            // First store call should not trigger sync
            await store.storeSessionConsoleLogs([log1])
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()

            // Second store call should trigger sync because limit is 2
            await store.storeSessionConsoleLogs([log2])
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
            const queuedMessages = getQueuedMessages(mockOutputs, 0)
            expect(queuedMessages).toEqual([
                { key: 'session1', value: expect.any(Buffer) },
                { key: 'session2', value: expect.any(Buffer) },
            ])
        })

        it('should handle batches larger than the limit', async () => {
            const log1 = createTestLog('1')
            const log2 = createTestLog('2')
            const log3 = createTestLog('3')

            // Store 3 logs at once
            await store.storeSessionConsoleLogs([log1, log2, log3])

            // Should trigger immediate sync due to exceeding limit
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
            const queuedMessages = getQueuedMessages(mockOutputs, 0)
            expect(queuedMessages).toEqual([
                { key: 'session1', value: expect.any(Buffer) },
                { key: 'session2', value: expect.any(Buffer) },
                { key: 'session3', value: expect.any(Buffer) },
            ])
        })

        it('should sync remaining messages on flush', async () => {
            const log1 = createTestLog('1')

            // Store one log (under limit)
            await store.storeSessionConsoleLogs([log1])
            expect(mockOutputs.queueMessages).not.toHaveBeenCalled()

            // Flush should sync remaining messages
            await store.flush()
            expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
            const queuedMessages = getQueuedMessages(mockOutputs, 0)
            expect(queuedMessages).toEqual([{ key: 'session1', value: expect.any(Buffer) }])
        })
    })
})
