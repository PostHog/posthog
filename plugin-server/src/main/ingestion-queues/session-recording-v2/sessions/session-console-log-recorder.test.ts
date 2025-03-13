import { DateTime } from 'luxon'

import { LogLevel } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'
import { ConsoleLogLevel, RRWebEventType } from '../rrweb-types'
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

        recorder = new SessionConsoleLogRecorder('test_session_id', 1, 'test_batch_id', mockConsoleLogStore)
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
        { sessionId = 'session_id', distinctId = 'distinct_id' } = {}
    ): ParsedMessageData => ({
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
    })

    describe('Console log counting', () => {
        it('should count console log events', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Test log message'],
                    timestamp: 1000,
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
                    timestamp: 1000,
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
                    timestamp: 1000,
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
                    timestamp: 1000,
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Test warning message'],
                    timestamp: 1500,
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Test error message'],
                    timestamp: 2000,
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Test log message 2'],
                    timestamp: 2500,
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
                    timestamp: 1000,
                    data: {},
                },
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 1500,
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
                    timestamp: 1000,
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
            const timestamp1 = 1687801200000 // 2023-06-26 12:00:00
            const timestamp2 = 1687801205000 // 2023-06-26 12:00:05
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
                    level: LogLevel.Info,
                    log_source: 'session_replay',
                    log_source_id: 'test_session_id',
                    instance_id: null,
                    timestamp: '2023-06-26 17:40:00.000',
                    batch_id: 'test_batch_id',
                },
            ])

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenNthCalledWith(2, [
                {
                    team_id: 1,
                    message: 'Second message',
                    level: LogLevel.Warn,
                    log_source: 'session_replay',
                    log_source_id: 'test_session_id',
                    instance_id: null,
                    timestamp: '2023-06-26 17:40:05.000',
                    batch_id: 'test_batch_id',
                },
            ])
        })

        it('should handle non-string payload elements', async () => {
            const timestamp = 1687801200000 // 2023-06-26 12:00:00
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
                    level: LogLevel.Info,
                    log_source: 'session_replay',
                    log_source_id: 'test_session_id',
                    instance_id: null,
                    timestamp: '2023-06-26 17:40:00.000',
                    batch_id: 'test_batch_id',
                },
            ])
        })
    })

    describe('Error handling', () => {
        it('should throw error when recording after end', async () => {
            const message = createMessage(
                'window1',
                [
                    {
                        type: RRWebEventType.Plugin,
                        timestamp: 1000,
                        data: {
                            plugin: 'rrweb/console@1',
                            payload: {
                                level: ConsoleLogLevel.Log,
                                content: ['Test message'],
                            },
                        },
                    },
                ],
                { sessionId: 'session_error_handling_1', distinctId: 'user_7' }
            )

            await recorder.recordMessage(message)
            recorder.end()

            await expect(recorder.recordMessage(message)).rejects.toThrow(
                'Cannot record message after end() has been called'
            )
        })

        it('should throw error when calling end multiple times', async () => {
            const message = createMessage(
                'window1',
                [
                    {
                        type: RRWebEventType.Plugin,
                        timestamp: 1000,
                        data: {
                            plugin: 'rrweb/console@1',
                            payload: {
                                level: ConsoleLogLevel.Log,
                                content: ['Test message'],
                            },
                        },
                    },
                ],
                { sessionId: 'session_error_handling_2', distinctId: 'user_8' }
            )

            await recorder.recordMessage(message)
            recorder.end()

            expect(() => recorder.end()).toThrow('end() has already been called')
        })
    })

    describe('Multiple windows', () => {
        it('should count console events from multiple windows', async () => {
            const message1 = createMessage(
                'window1',
                [
                    {
                        type: RRWebEventType.Plugin,
                        timestamp: 1000,
                        data: {
                            plugin: 'rrweb/console@1',
                            payload: {
                                level: ConsoleLogLevel.Log,
                                content: ['Window 1 log'],
                            },
                        },
                    },
                ],
                { sessionId: 'session_multi_window_1', distinctId: 'user_9' }
            )

            const message2 = createMessage(
                'window2',
                [
                    {
                        type: RRWebEventType.Plugin,
                        timestamp: 2000,
                        data: {
                            plugin: 'rrweb/console@1',
                            payload: {
                                level: ConsoleLogLevel.Error,
                                content: ['Window 2 error'],
                            },
                        },
                    },
                ],
                { sessionId: 'session_multi_window_1', distinctId: 'user_9' }
            )

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
            { input: 'info', expected: LogLevel.Info },
            { input: 'log', expected: LogLevel.Info },
            { input: 'debug', expected: LogLevel.Info },
            { input: 'trace', expected: LogLevel.Info },
            { input: 'dir', expected: LogLevel.Info },
            { input: 'dirxml', expected: LogLevel.Info },
            { input: 'group', expected: LogLevel.Info },
            { input: 'groupCollapsed', expected: LogLevel.Info },
            { input: 'count', expected: LogLevel.Info },
            { input: 'timeEnd', expected: LogLevel.Info },
            { input: 'timeLog', expected: LogLevel.Info },
            // Warn level mappings
            { input: 'warn', expected: LogLevel.Warn },
            { input: 'countReset', expected: LogLevel.Warn },
            // Error level mappings
            { input: 'error', expected: LogLevel.Error },
            { input: 'assert', expected: LogLevel.Error },
        ]

        test.each(testCases)('maps browser level $input to $expected', async ({ input, expected }) => {
            const event = createConsoleLogEvent({
                level: input as unknown,
                payload: ['test message'],
                timestamp: 1000,
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
                { level: 'unknown', expected: LogLevel.Info },
                { level: '', expected: LogLevel.Info },
                { level: undefined, expected: LogLevel.Info },
                { level: null, expected: LogLevel.Info },
                { level: 123, expected: LogLevel.Info },
            ]

            for (const { level, expected } of edgeCases) {
                const event = createConsoleLogEvent({
                    level,
                    payload: ['test message'],
                    timestamp: 1000,
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
                    timestamp: 1000,
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate message'],
                    timestamp: 2000,
                }),
            ]

            await recorder.recordMessage(
                createMessage('window1', events, { sessionId: 'session_dedup_1', distinctId: 'user_10' })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: LogLevel.Info,
                    message: 'Duplicate message',
                }),
            ])
        })

        it('should not deduplicate same messages with different levels', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Same message'],
                    timestamp: 1000,
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Same message'],
                    timestamp: 2000,
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Same message'],
                    timestamp: 3000,
                }),
            ]

            await recorder.recordMessage(
                createMessage('window1', events, { sessionId: 'session_dedup_2', distinctId: 'user_11' })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: LogLevel.Info,
                    message: 'Same message',
                }),
                expect.objectContaining({
                    level: LogLevel.Warn,
                    message: 'Same message',
                }),
                expect.objectContaining({
                    level: LogLevel.Error,
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
                        timestamp: 1000,
                    }),
                ],
                { sessionId: 'session_dedup_3', distinctId: 'user_12' }
            )

            // Add events from window2 to the same message
            message.eventsByWindowId['window2'] = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate message'],
                    timestamp: 2000,
                }),
            ]

            await recorder.recordMessage(message)

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: LogLevel.Info,
                    message: 'Duplicate message',
                }),
            ])
        })

        it('should maintain correct counts even with deduplication', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate info'],
                    timestamp: 1000,
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Duplicate info'],
                    timestamp: 2000,
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Duplicate warn'],
                    timestamp: 3000,
                }),
                createConsoleLogEvent({
                    level: 'warn',
                    payload: ['Duplicate warn'],
                    timestamp: 4000,
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Duplicate error'],
                    timestamp: 5000,
                }),
                createConsoleLogEvent({
                    level: 'error',
                    payload: ['Duplicate error'],
                    timestamp: 6000,
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
                    level: LogLevel.Info,
                    message: 'Duplicate info',
                }),
                expect.objectContaining({
                    level: LogLevel.Warn,
                    message: 'Duplicate warn',
                }),
                expect.objectContaining({
                    level: LogLevel.Error,
                    message: 'Duplicate error',
                }),
            ])
        })

        it('should preserve different messages with same level', async () => {
            const events = [
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['First unique message'],
                    timestamp: 1000,
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Second unique message'],
                    timestamp: 2000,
                }),
                createConsoleLogEvent({
                    level: 'info',
                    payload: ['Third unique message'],
                    timestamp: 3000,
                }),
            ]

            await recorder.recordMessage(
                createMessage('window1', events, { sessionId: 'session_dedup_5', distinctId: 'user_14' })
            )

            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenCalledWith([
                expect.objectContaining({
                    level: LogLevel.Info,
                    message: 'First unique message',
                }),
                expect.objectContaining({
                    level: LogLevel.Info,
                    message: 'Second unique message',
                }),
                expect.objectContaining({
                    level: LogLevel.Info,
                    message: 'Third unique message',
                }),
            ])
        })
    })
})
