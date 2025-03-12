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

    const createMessage = (windowId: string, events: any[]): ParsedMessageData => ({
        distinct_id: 'distinct_id',
        session_id: 'session_id',
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
    })

    describe('Error handling', () => {
        it('should throw error when recording after end', async () => {
            const message = createMessage('window1', [
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
            ])

            await recorder.recordMessage(message)
            recorder.end()

            await expect(recorder.recordMessage(message)).rejects.toThrow(
                'Cannot record message after end() has been called'
            )
        })

        it('should throw error when calling end multiple times', async () => {
            const message = createMessage('window1', [
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
            ])

            await recorder.recordMessage(message)
            recorder.end()

            expect(() => recorder.end()).toThrow('end() has already been called')
        })
    })

    describe('Multiple windows', () => {
        it('should count console events from multiple windows', async () => {
            const message1 = createMessage('window1', [
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
            ])

            const message2 = createMessage('window2', [
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

            await recorder.recordMessage(createMessage('window1', [event]))

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

                await recorder.recordMessage(createMessage('window1', [event]))

                expect(mockConsoleLogStore.storeSessionConsoleLogs).toHaveBeenLastCalledWith([
                    expect.objectContaining({
                        level: expected,
                        message: 'test message',
                    }),
                ])
            }
        })
    })
})
