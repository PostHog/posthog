import { DateTime } from 'luxon'

import { ParsedMessageData } from '../kafka/types'
import { ConsoleLogLevel, RRWebEventType } from '../rrweb-types'
import { SessionConsoleLogRecorder } from './session-console-log-recorder'

describe('SessionConsoleLogRecorder', () => {
    let recorder: SessionConsoleLogRecorder

    beforeEach(() => {
        recorder = new SessionConsoleLogRecorder('test_session_id', 1, 'test_batch_id')
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
        it('should count console log events', () => {
            const events = [
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 1000,
                    data: {
                        plugin: 'rrweb/console@1',
                        payload: {
                            level: ConsoleLogLevel.Log,
                            content: ['Test log message'],
                        },
                    },
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(1)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(0)
        })

        it('should count console warn events', () => {
            const events = [
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 1000,
                    data: {
                        plugin: 'rrweb/console@1',
                        payload: {
                            level: ConsoleLogLevel.Warn,
                            content: ['Test warning message'],
                        },
                    },
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(0)
            expect(result.consoleWarnCount).toBe(1)
            expect(result.consoleErrorCount).toBe(0)
        })

        it('should count console error events', () => {
            const events = [
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 1000,
                    data: {
                        plugin: 'rrweb/console@1',
                        payload: {
                            level: ConsoleLogLevel.Error,
                            content: ['Test error message'],
                        },
                    },
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(0)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(1)
        })

        it('should count multiple console events of different types', () => {
            const events = [
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 1000,
                    data: {
                        plugin: 'rrweb/console@1',
                        payload: {
                            level: ConsoleLogLevel.Log,
                            content: ['Test log message 1'],
                        },
                    },
                },
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 1500,
                    data: {
                        plugin: 'rrweb/console@1',
                        payload: {
                            level: ConsoleLogLevel.Warn,
                            content: ['Test warning message'],
                        },
                    },
                },
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 2000,
                    data: {
                        plugin: 'rrweb/console@1',
                        payload: {
                            level: ConsoleLogLevel.Error,
                            content: ['Test error message'],
                        },
                    },
                },
                {
                    type: RRWebEventType.Plugin,
                    timestamp: 2500,
                    data: {
                        plugin: 'rrweb/console@1',
                        payload: {
                            level: ConsoleLogLevel.Log,
                            content: ['Test log message 2'],
                        },
                    },
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(2)
            expect(result.consoleWarnCount).toBe(1)
            expect(result.consoleErrorCount).toBe(1)
        })

        it('should not count non-console events', () => {
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

            recorder.recordMessage(message)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(0)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(0)
        })
    })

    describe('Error handling', () => {
        it('should throw error when recording after end', () => {
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

            recorder.recordMessage(message)
            recorder.end()

            expect(() => recorder.recordMessage(message)).toThrow('Cannot record message after end() has been called')
        })

        it('should throw error when calling end multiple times', () => {
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

            recorder.recordMessage(message)
            recorder.end()

            expect(() => recorder.end()).toThrow('end() has already been called')
        })
    })

    describe('Multiple windows', () => {
        it('should count console events from multiple windows', () => {
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

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = recorder.end()

            expect(result.consoleLogCount).toBe(1)
            expect(result.consoleWarnCount).toBe(0)
            expect(result.consoleErrorCount).toBe(1)
        })
    })
})
