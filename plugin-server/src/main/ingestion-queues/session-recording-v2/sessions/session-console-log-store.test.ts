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
                level: ConsoleLogLevel.Log,
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
        await store.flush()

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
        await store.flush()
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
            await store.flush()
            expect(SessionBatchMetrics.incrementConsoleLogsStored).toHaveBeenCalledWith(2)
        })

        it('should not increment metric for empty logs array', async () => {
            await store.storeSessionConsoleLogs([])
            await store.flush()
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
            await store.flush()
            expect(SessionBatchMetrics.incrementConsoleLogsStored).not.toHaveBeenCalled()
        })
    })

    describe('promise limit and sync behavior', () => {
        let mockProducer: jest.Mocked<KafkaProducerWrapper>
        let store: SessionConsoleLogStore
        let resolveProducerPromises: (() => void)[]

        beforeEach(() => {
            resolveProducerPromises = []
            mockProducer = {
                queueMessages: jest.fn().mockImplementation(() => {
                    return new Promise<void>((resolve) => {
                        // Store the resolve function so we can control when this promise resolves
                        resolveProducerPromises.push(resolve)
                    })
                }),
                flush: jest.fn().mockResolvedValue(undefined),
            } as unknown as jest.Mocked<KafkaProducerWrapper>

            // Set promise limit to 1 to make testing easier
            store = new SessionConsoleLogStore(mockProducer, 'log_entries_v2', { promiseLimit: 1 })
        })

        const createTestLog = (id: string): ConsoleLogEntry => ({
            team_id: 1,
            message: `Test message ${id}`,
            level: ConsoleLogLevel.Log,
            log_source: 'session_replay',
            log_source_id: `session${id}`,
            instance_id: null,
            timestamp: makeTimestamp('2025-01-01 10:00:00.000'),
            batch_id: `batch${id}`,
        })

        it('should not await producer promise when storing logs initially', async () => {
            const log = createTestLog('1')

            // This should return immediately without waiting for the producer
            const storePromise = store.storeSessionConsoleLogs([log])

            // Verify that storeSessionConsoleLogs resolves before the producer promise
            let storeResolved = false
            void storePromise.then(() => {
                storeResolved = true
            })

            await new Promise((resolve) => setTimeout(resolve, 10))
            expect(storeResolved).toBe(true)
            expect(resolveProducerPromises.length).toBe(1)
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)

            // Now when we flush, it should wait for all producer promises
            const flushPromise = store.flush()
            let flushResolved = false
            void flushPromise.then(() => {
                flushResolved = true
            })

            await new Promise((resolve) => setTimeout(resolve, 10))
            expect(flushResolved).toBe(false)

            // Resolve the producer promise
            resolveProducerPromises[0]()

            // Now flush should complete
            await flushPromise
            expect(mockProducer.flush).toHaveBeenCalledTimes(1)
        })

        it('should handle sync correctly with multiple messages', async () => {
            const log1 = createTestLog('1')
            const log2 = createTestLog('2')
            const log3 = createTestLog('3')

            // First store call should return immediately
            const store1Promise = store.storeSessionConsoleLogs([log1])
            let store1Resolved = false
            void store1Promise.then(() => {
                store1Resolved = true
            })

            // Second store call should trigger a sync because limit is 1
            const store2Promise = store.storeSessionConsoleLogs([log2])
            let store2Resolved = false
            void store2Promise.then(() => {
                store2Resolved = true
            })

            // Third store call should queue up behind the sync
            const store3Promise = store.storeSessionConsoleLogs([log3])
            let store3Resolved = false
            void store3Promise.then(() => {
                store3Resolved = true
            })

            // First store should have resolved immediately
            await new Promise((resolve) => setTimeout(resolve, 10))
            expect(store1Resolved).toBe(true)
            expect(store2Resolved).toBe(false)
            expect(store3Resolved).toBe(false)
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(1)
            expect(resolveProducerPromises.length).toBe(1)

            // Resolve first producer promise
            resolveProducerPromises[0]()

            // Wait a bit for promises to resolve
            await new Promise((resolve) => setTimeout(resolve, 10))

            // Second store should now be resolved and third should be queued
            expect(store2Resolved).toBe(true)
            expect(store3Resolved).toBe(false)
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(2)
            expect(resolveProducerPromises.length).toBe(2)

            // Resolve second producer promise
            resolveProducerPromises[1]()

            // Wait a bit for promises to resolve
            await new Promise((resolve) => setTimeout(resolve, 10))

            // All stores should be resolved now
            expect(store3Resolved).toBe(true)
            expect(mockProducer.queueMessages).toHaveBeenCalledTimes(3)
            expect(resolveProducerPromises.length).toBe(3)

            // Resolve final producer promise
            resolveProducerPromises[2]()

            // Flush should work as expected
            await store.flush()
            expect(mockProducer.flush).toHaveBeenCalledTimes(1)
        })
    })
})
