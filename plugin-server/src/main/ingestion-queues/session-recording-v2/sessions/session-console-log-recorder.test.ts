import { DateTime } from 'luxon'

import { ConsoleLogLevel, RRWebEventType } from '../rrweb-types'
import { MessageWithTeam } from '../teams/types'
import { SessionConsoleLogRecorder } from './session-console-log-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'

describe('SessionConsoleLogRecorder', () => {
    let recorder: SessionConsoleLogRecorder
    let mockConsoleLogStore: jest.Mocked<SessionConsoleLogStore>

    beforeEach(() => {
        mockConsoleLogStore = {
            storeSessionConsoleLogs: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionConsoleLogStore>

        recorder = new SessionConsoleLogRecorder(
            'test_session_id',
            1,
            'test_batch_id',
            mockConsoleLogStore,
            new Date('2024-03-15T10:00:00.000Z')
        )
    })

    const createConsoleLogEvent = ({
        level,
        payload,
        timestamp,
    }: {
        level: unknown
        payload: unknown[]
        timestamp: number
    }) => ({
        type: RRWebEventType.Plugin,
        timestamp,
        data: {
            plugin: 'rrweb/console@1',
            payload: {
                level,
                payload,
            },
        },
    })

    const createMessage = (
        windowId: string,
        events: any[],
        { sessionId = 'session_id', distinctId = 'distinct_id', teamId = 1, consoleLogIngestionEnabled = true } = {}
    ): MessageWithTeam => ({
        team: {
            teamId,
            consoleLogIngestionEnabled,
        },
        message: {
            distinct_id: distinctId,
            session_id: sessionId,
            eventsByWindowId: {
                [windowId]: events,
            },
            eventsRange: {
                start: DateTime.fromMillis(events[0]?.timestamp || 0),
                end: DateTime.fromMillis(events[events.length - 1]?.timestamp || 0),
            },
            snapshot_source: null,
            snapshot_library: null,
            metadata: {
                partition: 1,
                topic: 'test',
                offset: 0,
                timestamp: 0,
                rawSize: 0,
            },
        },
    })

    describe('Console log counting', () => {
        it('should count console log events', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Test log message'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(1)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(0)
        })

        it('should count console warn events', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Test warning message'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(0)
            expect(result.consoleWarnCount).toBe(1)
            expect(result.consoleErrorCount).toBe(0)
        })

        it('should count console error events', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Test error message'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(0)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(1)
        })

        it('should count multiple console events of different types', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Test log message 1'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Test warning message'],
                    timestamp: new Date('2024-03-15T10:00:01Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Test error message'],
                    timestamp: new Date('2024-03-15T10:00:02Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Test log message 2'],
                    timestamp: new Date('2024-03-15T10:00:03Z').getTime(),
                }),
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(2)
            expect(result.consoleWarnCount).toBe(1)
            expect(result.consoleErrorCount).toBe(1)
        })

        it('should not count non-console events', async () => {
            const events = [
                {
                    type: RRWebEventType.Meta,
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                    data: {},
                },
                {
                    type: RRWebEventType.Plugin,
                    timestamp: new Date('2024-03-15T10:00:01Z').getTime(),
                    data: {
                        plugin: 'some-other-plugin',
                        payload: {
                            level: 'log',
                            content: ['This should not be counted'],
                        },
                    },
                },
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(0)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(0)
        })

        it('should map log level to info for counting', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'log',
                    payload: ['Test log message'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(1)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(0)
        })

        it('should publish all fields correctly when storing console logs', async () => {
            const timestamp1 = new Date('2024-03-15T10:00:00Z').getTime()
            const timestamp2 = new Date('2024-03-15T10:00:01Z').getTime()
            const events1 = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['First message'],
                    timestamp: timestamp1,
                }),
            ]
            const events2 = [
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Second message'],
                    timestamp: timestamp2,
                }),
            ]
            const message1 = createMessage('window1', events1, {
                sessionId: 'session_id_1',
                distinctId: 'distinct_id_1',
            })
            const message2 = createMessage('window2', events2, {
                sessionId: 'session_id_2',
                distinctId: 'distinct_id_2',
            })

            await recorder.recordMessage(message1)
            await recorder.recordMessage(message2)

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenNthCalledWith(1, [
                {
                    team_id: 1,
                    message: 'First message',
                    level: ConsoleLogLevel.Info,
                    log_source: 'session_replay',
                    log_source_id: 'test_session_id',
                    instance_id: null,
                    timestamp: '2024-03-15 10:00:00.000',
                    batch_id: 'test_batch_id',
                },
            ])

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenNthCalledWith(2, [
                {
                    team_id: 1,
                    message: 'Second message',
                    level: ConsoleLogLevel.Warn,
                    log_source: 'session_replay',
                    log_source_id: 'test_session_id',
                    instance_id: null,
                    timestamp: '2024-03-15 10:00:01.000',
                    batch_id: 'test_batch_id',
                },
            ])
        })

        it('should handle non-string payload elements', async () => {
            const timestamp = new Date('2024-03-15T10:00:00Z').getTime()
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: [
                        'Message with',
                        { complex: 'object' },
                        123,
                        ['nested', 'array'],
                        'multiple strings',
                        null,
                        undefined,
                        true,
                        Symbol('test'),
                    ],
                    timestamp,
                }),
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                {
                    team_id: 1,
                    message: 'Message with multiple strings',
                    level: ConsoleLogLevel.Info,
                    log_source: 'session_replay',
                    log_source_id: 'test_session_id',
                    instance_id: null,
                    timestamp: '2024-03-15 10:00:00.000',
                    batch_id: 'test_batch_id',
                },
            ])
        })

        it('should ignore logs before switchover date', async () => {
            const switchoverDate = new Date('2024-03-15T10:00:00.000Z')
            const recorder = new SessionConsoleLogRecorder(
                'test_session_id',
                1,
                'test_batch_id',
                mockConsoleLogStore,
                switchoverDate
            )

            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Before switchover'],
                    timestamp: new Date('2024-03-15T09:59:59Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['After switchover'],
                    timestamp: new Date('2024-03-15T10:00:01Z').getTime(),
                }),
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(0)
            expect(result.consoleWarnCount).toBe(1)
            expect(result.consoleErrorCount).toBe(0)

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: ConsoleLogLevel.Warn,
                    message: 'After switchover',
                }),
            ])
        })

        it('should skip all logs when metadataSwitchoverDate is null', async () => {
            const recorder = new SessionConsoleLogRecorder(
                'test_session_id',
                1,
                'test_batch_id',
                mockConsoleLogStore,
                null
            )

            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Test info message'],
                    timestamp: 1000,
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Test warning message'],
                    timestamp: 2000,
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Test error message'],
                    timestamp: 3000,
                }),
            ]
            const message = createMessage('window1', events)

            await recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(0)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(0)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).not.toHaveBeenCalled()
        })
    })

    describe('Error handling', () => {
        it('should throw error when recording after end', async () => {
            const message = createMessage('window1', [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Test message'],
                    timestamp: 1000,
                }),
            ])

            await recorder.recordMessage(message)
            recorder.end()

            await expect(recorder.recordMessage(message)).rejects.toThrow(
                'Cannot record message after end() has been called'
            )
        })

        it('should throw error when calling end multiple times', async () => {
            const message = createMessage('window1', [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Test message'],
                    timestamp: 1000,
                }),
            ])

            await recorder.recordMessage(message)
            recorder.end()

            expect(() => recorder.end()).toThrow('end() has already been called')
        })
    })

    describe('Multiple windows', () => {
        it('should count console events from multiple windows', async () => {
            const message1 = createMessage('window1', [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Window 1 log'],
                    timestamp: new Date('2025-04-07T20:00:00.000Z').getTime(),
                }),
            ])

            const message2 = createMessage('window2', [
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Window 2 error'],
                    timestamp: new Date('2025-04-07T20:00:01.000Z').getTime(),
                }),
            ])

            await recorder.recordMessage(message1)
            await recorder.recordMessage(message2)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(1)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(1)
        })
    })

    describe('Log level mapping', () => {
        const testCases = [
            // Info level mappings
            { input: 'info', expected: ConsoleLogLevel.Info },
            { input: 'log', expected: ConsoleLogLevel.Info },
            { input: 'debug', expected: ConsoleLogLevel.Info },
            { input: 'trace', expected: ConsoleLogLevel.Info },
            { input: 'dir', expected: ConsoleLogLevel.Info },
            { input: 'dirxml', expected: ConsoleLogLevel.Info },
            { input: 'group', expected: ConsoleLogLevel.Info },
            { input: 'groupCollapsed', expected: ConsoleLogLevel.Info },
            { input: 'count', expected: ConsoleLogLevel.Info },
            { input: 'timeEnd', expected: ConsoleLogLevel.Info },
            { input: 'timeLog', expected: ConsoleLogLevel.Info },
            // Warn level mappings
            { input: 'warn', expected: ConsoleLogLevel.Warn },
            { input: 'countReset', expected: ConsoleLogLevel.Warn },
            // Error level mappings
            { input: 'error', expected: ConsoleLogLevel.Error },
            { input: 'assert', expected: ConsoleLogLevel.Error },
        ]

        test.each(testCases)('maps browser level $input to $expected', async ({ input, expected }) => {
            const event = createConsoleLogEvent({
                level: input as unknown,
                payload: ['test message'],
                timestamp: new Date('2025-01-01T10:00:00.000Z').getTime(),
            })

            await recorder.recordMessage(
                createMessage('window1', [event], {
                    sessionId: `session_level_${input}`,
                    distinctId: 'user_level_mapper',
                })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: expected,
                    message: 'test message',
                }),
            ])
        })

        it('handles edge cases', async () => {
            const edgeCases = [
                { level: 'unknown', expected: ConsoleLogLevel.Info },
                { level: '', expected: ConsoleLogLevel.Info },
                { level: undefined, expected: ConsoleLogLevel.Info },
                { level: null, expected: ConsoleLogLevel.Info },
                { level: 123, expected: ConsoleLogLevel.Info },
            ]

            for (const { level, expected } of edgeCases) {
                const event = createConsoleLogEvent({
                    level,
                    payload: ['test message'],
                    timestamp: new Date('2025-01-01T10:00:00.000Z').getTime(),
                })

                await recorder.recordMessage(
                    createMessage('window1', [event], {
                        sessionId: `session_edge_${String(level)}`,
                        distinctId: 'user_edge_cases',
                    })
                )

                expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenLastCalledWith([
                    expect.objectContaining({
                        level: expected,
                        message: 'test message',
                    }),
                ])
            }
        })
    })

    describe('Deduplication', () => {
        it('should deduplicate identical messages with same level', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate message'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate message'],
                    timestamp: new Date('2024-03-15T10:00:01Z').getTime(),
                }),
            ]

            await recorder.recordMessage(
                createMessage('window1', events, { sessionId: 'session_dedup_1', distinctId: 'user_10' })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: ConsoleLogLevel.Info,
                    message: 'Duplicate message',
                }),
            ])
        })

        it('should not deduplicate same messages with different levels', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Same message'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Same message'],
                    timestamp: new Date('2024-03-15T10:00:01Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Same message'],
                    timestamp: new Date('2024-03-15T10:00:02Z').getTime(),
                }),
            ]

            await recorder.recordMessage(
                createMessage('window1', events, { sessionId: 'session_dedup_2', distinctId: 'user_11' })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: ConsoleLogLevel.Info,
                    message: 'Same message',
                }),
                expect.objectContaining({
                    level: ConsoleLogLevel.Warn,
                    message: 'Same message',
                }),
                expect.objectContaining({
                    level: ConsoleLogLevel.Error,
                    message: 'Same message',
                }),
            ])
        })

        it('should deduplicate across multiple windows', async () => {
            const message = createMessage(
                'window1',
                [
                    createConsoleLogEvent({
                        level: 'info',
                        payload: ['Duplicate message'],
                        timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                    }),
                ],
                { sessionId: 'session_dedup_3', distinctId: 'user_12' }
            )

            // Add events from window2 to the same message
            message.message.eventsByWindowId['window2'] = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate message'],
                    timestamp: new Date('2024-03-15T10:00:01Z').getTime(),
                }),
            ]

            await recorder.recordMessage(message)

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: ConsoleLogLevel.Info,
                    message: 'Duplicate message',
                }),
            ])
        })

        it('should maintain correct counts even with deduplication', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate info'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate info'],
                    timestamp: new Date('2024-03-15T10:00:01Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Duplicate warn'],
                    timestamp: new Date('2024-03-15T10:00:02Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Duplicate warn'],
                    timestamp: new Date('2024-03-15T10:00:03Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Duplicate error'],
                    timestamp: new Date('2024-03-15T10:00:04Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Duplicate error'],
                    timestamp: new Date('2024-03-15T10:00:05Z').getTime(),
                }),
            ]

            await recorder.recordMessage(
                createMessage('window1', events, { sessionId: 'session_dedup_4', distinctId: 'user_13' })
            )
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(2)
            expect(result.consoleWarnCount).toBe(2)
            expect(result.consoleErrorCount).toBe(2)

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: ConsoleLogLevel.Info,
                    message: 'Duplicate info',
                }),
                expect.objectContaining({
                    level: ConsoleLogLevel.Warn,
                    message: 'Duplicate warn',
                }),
                expect.objectContaining({
                    level: ConsoleLogLevel.Error,
                    message: 'Duplicate error',
                }),
            ])
        })

        it('should preserve different messages with same level', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['First unique message'],
                    timestamp: new Date('2024-03-15T10:00:00Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Second unique message'],
                    timestamp: new Date('2024-03-15T10:00:01Z').getTime(),
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Third unique message'],
                    timestamp: new Date('2024-03-15T10:00:02Z').getTime(),
                }),
            ]

            await recorder.recordMessage(
                createMessage('window1', events, { sessionId: 'session_dedup_5', distinctId: 'user_14' })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: ConsoleLogLevel.Info,
                    message: 'First unique message',
                }),
                expect.objectContaining({
                    level: ConsoleLogLevel.Info,
                    message: 'Second unique message',
                }),
                expect.objectContaining({
                    level: ConsoleLogLevel.Info,
                    message: 'Third unique message',
                }),
            ])
        })

        it('should not record logs when consoleLogIngestionEnabled is false', async () => {
            const now = DateTime.fromISO('2024-03-15T10:00:00Z')
            const message = createMessage(
                'window1',
                [
                    {
                        timestamp: now.toMillis(),
                        type: RRWebEventType.Plugin,
                        data: {
                            plugin: 'rrweb/console@1',
                            payload: {
                                level: 'log',
                                payload: ['test message'],
                            },
                        },
                    },
                ],
                { consoleLogIngestionEnabled: false }
            )

            await recorder.recordMessage(message)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).not.toHaveBeenCalled()

            const result = recorder.end()
            expect(result).toEqual({
                consoleLogCount: 0,
                consoleWarnCount: 0,
                consoleErrorCount: 0,
            })
        })
    })
})
