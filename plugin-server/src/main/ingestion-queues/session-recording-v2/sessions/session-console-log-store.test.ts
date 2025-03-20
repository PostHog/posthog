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

        store = new SessionConsoleLogStore(mockProducer, 'log_entries_v2')
    })

    it('should queue logs to kafka with correct data', async () => {
        const logs: ConsoleLogEntry[] = [
            {
                team_id: 1,
                message: 'Test log message',
                level: ConsoleLogLevel.Log,
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

        expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        expect(queuedMessage.topic).toBe('log_entries_v2')
        const queuedMessages = queuedMessage.messages
        const parsedLogs = queuedMessages.map((msg) => parseJSON(msg.value as string))

        expect(parsedLogs).toMatchObject([
            {
                team_id: 1,
                message: 'Test log message',
                level: 'log',
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
        expect(mockProducer.queueMessages).not.toHaveBeenCalled()
    })

    it('should handle producer errors', async () => {
        const error = new Error('Kafka producer error')
        mockProducer.queueMessages.mockRejectedValueOnce(error)

        const logs: ConsoleLogEntry[] = [
            {
                team_id: 1,
                message: 'Test log message',
                level: ConsoleLogLevel.Log,
                log_source: 'session_replay',
                log_source_id: 'session123',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                batch_id: 'batch123',
            },
        ]

        await expect(store.storeSessionConsoleLogs(logs)).rejects.toThrow(error)
    })

    it('should preserve batch IDs when storing logs', async () => {
        const logs: ConsoleLogEntry[] = [
            {
                team_id: 1,
                message: 'Test log message 1',
                level: ConsoleLogLevel.Log,
                log_source: 'session_replay',
                log_source_id: 'session1',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                batch_id: 'batch1',
            },
            {
                team_id: 1,
                message: 'Test log message 2',
                level: ConsoleLogLevel.Log,
                log_source: 'session_replay',
                log_source_id: 'session2',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:03.000'),
                batch_id: 'batch2',
            },
        ]

        await store.storeSessionConsoleLogs(logs)

        const queuedMessage = mockProducer.queueMessages.mock.calls[0][0] as TopicMessage
        const parsedLogs = queuedMessage.messages.map((msg) => parseJSON(msg.value as string))

        expect(parsedLogs[0].batch_id).toBe('batch1')
        expect(parsedLogs[1].batch_id).toBe('batch2')
    })

    it('should not produce if topic is empty', async () => {
        store = new SessionConsoleLogStore(mockProducer, '')

        const logs: ConsoleLogEntry[] = [
            {
                team_id: 1,
                message: 'Test log message',
                level: ConsoleLogLevel.Log,
                log_source: 'session_replay',
                log_source_id: 'session123',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                batch_id: 'batch123',
            },
        ]

        await store.storeSessionConsoleLogs(logs)
        expect(mockProducer.queueMessages).not.toHaveBeenCalled()
    })

    it('should use custom topic when provided', async () => {
        const customTopic = 'custom_log_entries_topic'
        store = new SessionConsoleLogStore(mockProducer, customTopic)

        const logs: ConsoleLogEntry[] = [
            {
                team_id: 1,
                message: 'Test log message',
                level: ConsoleLogLevel.Log,
                log_source: 'session_replay',
                log_source_id: 'session123',
                instance_id: null,
                timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                batch_id: 'batch123',
            },
        ]

        await store.storeSessionConsoleLogs(logs)

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
                    level: ConsoleLogLevel.Log,
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
            expect(SessionBatchMetrics.incrementConsoleLogsStored).toHaveBeenCalledWith(2)
        })

        it('should not increment metric for empty logs array', async () => {
            await store.storeSessionConsoleLogs([])
            expect(SessionBatchMetrics.incrementConsoleLogsStored).not.toHaveBeenCalled()
        })

        it('should not increment metric when topic is empty', async () => {
            store = new SessionConsoleLogStore(mockProducer, '')
            const logs: ConsoleLogEntry[] = [
                {
                    team_id: 1,
                    message: 'Test log message',
                    level: ConsoleLogLevel.Log,
                    log_source: 'session_replay',
                    log_source_id: 'session123',
                    instance_id: null,
                    timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                    batch_id: 'batch123',
                },
            ]

            await store.storeSessionConsoleLogs(logs)
            expect(SessionBatchMetrics.incrementConsoleLogsStored).not.toHaveBeenCalled()
        })

        it('should not increment metric if producer fails', async () => {
            const error = new Error('Kafka producer error')
            mockProducer.queueMessages.mockRejectedValueOnce(error)

            const logs: ConsoleLogEntry[] = [
                {
                    team_id: 1,
                    message: 'Test log message',
                    level: ConsoleLogLevel.Log,
                    log_source: 'session_replay',
                    log_source_id: 'session123',
                    instance_id: null,
                    timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
                    batch_id: 'batch123',
                },
            ]

            await expect(store.storeSessionConsoleLogs(logs)).rejects.toThrow(error)
            expect(SessionBatchMetrics.incrementConsoleLogsStored).not.toHaveBeenCalled()
        })
    })
})
