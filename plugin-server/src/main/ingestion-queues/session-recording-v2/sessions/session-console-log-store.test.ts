import { KafkaProducerWrapper, TopicMessage } from '../../../../kafka/producer'
import { ClickHouseTimestamp } from '../../../../types'
import { parseJSON } from '../../../../utils/json-parse'
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

describe('SessionConsoleLogStore', () => {
    let store: SessionConsoleLogStore
    let mockProducer: jest.Mocked<KafkaProducerWrapper>

    beforeEach(() => {
        jest.clearAllMocks()
        mockProducer = {
            queueMessages: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<KafkaProducerWrapper>

        store = new SessionConsoleLogStore(mockProducer, 'log_entries_v2', { messageLimit: 1000 })
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

        expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        expect(queuedMessage.topic).toBe('log_entries_v2')
        const queuedMessages = queuedMessage.messages
        const parsedLogs = queuedMessages.map((msg) => parseJSON(msg.value as string))

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
        expect(mockProducer.queueMessages).not.toHaveBeenCalled()
    })

    it('should handle producer errors', async () => {
        const error = new Error('Kafka producer error')
        mockProducer.queueMessages.mockRejectedValueOnce(error)

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

        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        const parsedLogs = queuedMessage.messages.map((msg) => parseJSON(msg.value as string))

        expect(parsedLogs[0].batch_id).toBe('batch1')
        expect(parsedLogs[1].batch_id).toBe('batch2')
    })

    it('should not produce if topic is empty', async () => {
        store = new SessionConsoleLogStore(mockProducer, '', { messageLimit: 1000 })

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
        await store.flush()
        expect(mockProducer.queueMessages).not.toHaveBeenCalled()
    })

    it('should use custom topic when provided', async () => {
        const customTopic = 'custom_log_entries_topic'
        store = new SessionConsoleLogStore(mockProducer, customTopic, { messageLimit: 1000 })

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
        await store.flush()

        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        expect(queuedMessage.topic).toBe(customTopic)
    })

    describe('flush behavior', () => {
        it('should call producer flush', async () => {
            await store.flush()
            expect(mockProducer.flush).toHaveBeenCalledTimes(1)
        })

        it('should handle producer flush errors', async () => {
            const error = new Error('Flush error')
            mockProducer.flush.mockRejectedValueOnce(error)
            await expect(store.flush()).rejects.toThrow(error)
        })
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

        it('should not increment metric when topic is empty', async () => {
            store = new SessionConsoleLogStore(mockProducer, '', { messageLimit: 1000 })
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
            await store.flush()
            expect(SessionBatchMetrics.incrementConsoleLogsStored).not.toHaveBeenCalled()
        })
    })

    describe('message limit and sync behavior', () => {
        let mockProducer: jest.Mocked<KafkaProducerWrapper>
        let store: SessionConsoleLogStore

        beforeEach(() => {
            mockProducer = {
                queueMessages: jest.fn().mockResolvedValue(undefined),
                flush: jest.fn().mockResolvedValue(undefined),
            } as unknown as jest.Mocked<KafkaProducerWrapper>

            // Set message limit to 2 to make testing easier
            store = new SessionConsoleLogStore(mockProducer, 'log_entries_v2', { messageLimit: 2 })
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
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()

            // Second store call should trigger sync because limit is 2
            await store.storeSessionConsoleLogs([log2])
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(mockProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'log_entries_v2',
                messages: [
                    { key: 'session1', value: expect.any(String) },
                    { key: 'session2', value: expect.any(String) },
                ],
            })
        })

        it('should handle batches larger than the limit', async () => {
            const log1 = createTestLog('1')
            const log2 = createTestLog('2')
            const log3 = createTestLog('3')

            // Store 3 logs at once
            await store.storeSessionConsoleLogs([log1, log2, log3])

            // Should trigger immediate sync due to exceeding limit
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(mockProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'log_entries_v2',
                messages: [
                    { key: 'session1', value: expect.any(String) },
                    { key: 'session2', value: expect.any(String) },
                    { key: 'session3', value: expect.any(String) },
                ],
            })
        })

        it('should sync remaining messages on flush', async () => {
            const log1 = createTestLog('1')

            // Store one log (under limit)
            await store.storeSessionConsoleLogs([log1])
            expect(mockProducer.queueMessages).not.toHaveBeenCalled()

            // Flush should sync remaining messages
            await store.flush()
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(mockProducer.queueMessages).toHaveBeenCalledWith({
                topic: 'log_entries_v2',
                messages: [{ key: 'session1', value: expect.any(String) }],
            })
            expect(mockProducer.flush).toHaveBeenCalled()
        })
    })
})
