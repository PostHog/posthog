import { PassThrough } from 'stream'

import { SessionBatchMetrics } from '../../../../../src/main/ingestion-queues/session-recording-v2/sessions/metrics'
import {
    SessionBatchRecorder,
    SessionBatchRecorderInterface,
    SessionBatchWriter,
} from '../../../../../src/main/ingestion-queues/session-recording-v2/sessions/session-batch-recorder'
import { MessageWithTeam } from '../../../../../src/main/ingestion-queues/session-recording-v2/teams/types'

// RRWeb event type constants
const enum EventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
}

interface RRWebEvent {
    type: EventType
    timestamp: number
    data: Record<string, any>
}

interface MessageMetadata {
    partition?: number
    topic?: string
    offset?: number
    timestamp?: number
    rawSize?: number
}

// Add to the top of the file, after other mocks
jest.mock('../../../../../src/main/ingestion-queues/session-recording-v2/sessions/metrics', () => ({
    SessionBatchMetrics: {
        incrementBatchesFlushed: jest.fn(),
        incrementSessionsFlushed: jest.fn(),
        incrementEventsFlushed: jest.fn(),
        incrementBytesWritten: jest.fn(),
    },
}))

describe('SessionBatchRecorder', () => {
    let recorder: SessionBatchRecorderInterface
    let mockWriter: jest.Mocked<SessionBatchWriter>
    let mockStream: PassThrough
    let mockFinish: () => Promise<void>

    beforeEach(() => {
        mockStream = new PassThrough()
        mockFinish = jest.fn().mockResolvedValue(undefined)
        mockWriter = {
            open: jest.fn().mockImplementation(() =>
                Promise.resolve({
                    stream: mockStream,
                    finish: mockFinish,
                })
            ),
        }
        recorder = new SessionBatchRecorder(mockWriter)

        // Reset metrics mocks
        jest.mocked(SessionBatchMetrics.incrementBatchesFlushed).mockClear()
        jest.mocked(SessionBatchMetrics.incrementSessionsFlushed).mockClear()
        jest.mocked(SessionBatchMetrics.incrementEventsFlushed).mockClear()
        jest.mocked(SessionBatchMetrics.incrementBytesWritten).mockClear()
    })

    const createMessage = (
        sessionId: string,
        events: RRWebEvent[],
        metadata: MessageMetadata = {}
    ): MessageWithTeam => ({
        team: {
            teamId: 1,
            consoleLogIngestionEnabled: false,
        },
        message: {
            distinct_id: 'distinct_id',
            session_id: sessionId,
            eventsByWindowId: {
                window1: events,
            },
            eventsRange: {
                start: events[0]?.timestamp || 0,
                end: events[events.length - 1]?.timestamp || 0,
            },
            metadata: {
                partition: 1,
                topic: 'test',
                offset: 0,
                timestamp: 0,
                rawSize: 0,
                ...metadata,
            },
        },
    })

    const parseLines = (output: string): [string, RRWebEvent][] => {
        return output
            .trim()
            .split('\n')
            .map((line) => {
                const [windowId, event] = JSON.parse(line)
                return [windowId, event]
            })
    }

    const captureOutput = (stream: PassThrough): Promise<string> => {
        return new Promise<string>((resolve) => {
            let streamData = ''
            stream.on('data', (chunk) => {
                streamData += chunk
            })
            stream.on('end', () => {
                resolve(streamData)
            })
        })
    }

    describe('recording and writing', () => {
        it('should process and flush a single session', async () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                },
            ])

            recorder.record(message)
            const outputPromise = captureOutput(mockStream)
            await recorder.flush()

            expect(mockWriter.open).toHaveBeenCalled()
            expect(mockFinish).toHaveBeenCalled()

            const output = await outputPromise
            const lines = parseLines(output)
            expect(lines).toEqual([['window1', message.message.eventsByWindowId.window1[0]]])
            expect(output.endsWith('\n')).toBe(true)
        })

        it('should handle multiple sessions in parallel', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.Meta,
                        timestamp: 1000,
                        data: { href: 'https://example.com' },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Custom,
                        timestamp: 2000,
                        data: { tag: 'user-interaction' },
                    },
                ]),
            ]

            messages.forEach((message) => recorder.record(message))
            const outputPromise = captureOutput(mockStream)
            await recorder.flush()

            expect(mockWriter.open).toHaveBeenCalled()
            expect(mockFinish).toHaveBeenCalled()

            const output = await outputPromise
            const lines = parseLines(output)
            expect(lines).toEqual([
                ['window1', messages[0].message.eventsByWindowId.window1[0]],
                ['window1', messages[1].message.eventsByWindowId.window1[0]],
            ])
            expect(output.endsWith('\n')).toBe(true)
        })

        it('should accumulate events for the same session', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                    },
                ]),
                createMessage('session1', [
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                    },
                ]),
            ]

            messages.forEach((message) => recorder.record(message))
            const outputPromise = captureOutput(mockStream)
            await recorder.flush()

            expect(mockWriter.open).toHaveBeenCalled()
            expect(mockFinish).toHaveBeenCalled()

            const output = await outputPromise
            const lines = parseLines(output)
            expect(lines).toEqual([
                ['window1', messages[0].message.eventsByWindowId.window1[0]],
                ['window1', messages[1].message.eventsByWindowId.window1[0]],
            ])
            expect(output.endsWith('\n')).toBe(true)
        })

        it('should handle empty events array', async () => {
            const message = createMessage('session1', [])
            const bytesWritten = recorder.record(message)

            const outputPromise = captureOutput(mockStream)
            await recorder.flush()

            expect(mockWriter.open).toHaveBeenCalled()
            expect(mockFinish).toHaveBeenCalled()

            const output = await outputPromise
            expect(output).toBe('')
            expect(bytesWritten).toBe(0)
        })

        it('should group events by session when interleaved', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 1100,
                        data: { href: 'https://example.com' },
                    },
                ]),
                createMessage('session1', [
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Custom,
                        timestamp: 2100,
                        data: { tag: 'user-interaction' },
                    },
                ]),
            ]

            messages.forEach((message) => recorder.record(message))
            const outputPromise = captureOutput(mockStream)
            await recorder.flush()

            expect(mockWriter.open).toHaveBeenCalled()
            expect(mockFinish).toHaveBeenCalled()

            const output = await outputPromise
            const lines = parseLines(output)

            // Events should be grouped by session, maintaining chronological order within each session
            expect(lines).toEqual([
                // All session1 events
                ['window1', messages[0].message.eventsByWindowId.window1[0]],
                ['window1', messages[2].message.eventsByWindowId.window1[0]],
                // All session2 events
                ['window1', messages[1].message.eventsByWindowId.window1[0]],
                ['window1', messages[3].message.eventsByWindowId.window1[0]],
            ])
            expect(output.endsWith('\n')).toBe(true)
        })
    })

    describe('flushing behavior', () => {
        it('should clear sessions after flush', async () => {
            const stream1 = new PassThrough()
            const stream2 = new PassThrough()
            const finish1 = jest.fn().mockResolvedValue(undefined)
            const finish2 = jest.fn().mockResolvedValue(undefined)

            mockWriter.open
                .mockResolvedValueOnce({ stream: stream1, finish: finish1 })
                .mockResolvedValueOnce({ stream: stream2, finish: finish2 })

            const message1 = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                },
            ])

            const message2 = createMessage('session1', [
                {
                    type: EventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                },
            ])

            recorder.record(message1)
            const outputPromise1 = captureOutput(stream1)
            await recorder.flush()

            expect(mockWriter.open).toHaveBeenCalledTimes(1)
            expect(finish1).toHaveBeenCalledTimes(1)
            expect(finish2).not.toHaveBeenCalled()
            const output1 = await outputPromise1

            // Record another message after flush
            recorder.record(message2)
            const outputPromise2 = captureOutput(stream2)
            await recorder.flush()

            expect(mockWriter.open).toHaveBeenCalledTimes(2)
            expect(finish1).toHaveBeenCalledTimes(1)
            expect(finish2).toHaveBeenCalledTimes(1)
            const output2 = await outputPromise2

            // Each output should only contain the events from its own batch
            const lines1 = parseLines(output1)
            const lines2 = parseLines(output2)
            expect(lines1).toEqual([['window1', message1.message.eventsByWindowId.window1[0]]])
            expect(lines2).toEqual([['window1', message2.message.eventsByWindowId.window1[0]]])
        })

        it('should not output anything on second flush if no new events', async () => {
            const stream1 = new PassThrough()
            const stream2 = new PassThrough()
            const finish1 = jest.fn().mockResolvedValue(undefined)
            const finish2 = jest.fn().mockResolvedValue(undefined)

            mockWriter.open
                .mockResolvedValueOnce({ stream: stream1, finish: finish1 })
                .mockResolvedValueOnce({ stream: stream2, finish: finish2 })

            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            recorder.record(message)
            await recorder.flush()
            expect(mockWriter.open).toHaveBeenCalledTimes(1)
            expect(finish1).toHaveBeenCalledTimes(1)
            expect(finish2).not.toHaveBeenCalled()

            const outputPromise = captureOutput(stream2)
            await recorder.flush()
            const output = await outputPromise

            expect(output).toBe('')
            expect(mockWriter.open).toHaveBeenCalledTimes(2)
            expect(finish1).toHaveBeenCalledTimes(1)
            expect(finish2).toHaveBeenCalledTimes(1)
        })
    })

    describe('partition handling', () => {
        it('should flush all partitions', async () => {
            const messages = [
                createMessage(
                    'session1',
                    [
                        {
                            type: EventType.FullSnapshot,
                            timestamp: 1000,
                            data: { source: 1 },
                        },
                    ],
                    { partition: 1 }
                ),
                createMessage(
                    'session2',
                    [
                        {
                            type: EventType.IncrementalSnapshot,
                            timestamp: 2000,
                            data: { source: 2 },
                        },
                    ],
                    { partition: 2 }
                ),
            ]

            messages.forEach((message) => recorder.record(message))
            const outputPromise = captureOutput(mockStream)
            await recorder.flush()

            const output = await outputPromise
            const lines = parseLines(output)

            expect(lines).toEqual([
                ['window1', messages[0].message.eventsByWindowId.window1[0]],
                ['window1', messages[1].message.eventsByWindowId.window1[0]],
            ])
            expect(mockWriter.open).toHaveBeenCalledTimes(1)
            expect(mockFinish).toHaveBeenCalledTimes(1)
        })

        it('should not flush discarded partitions', async () => {
            const messages = [
                createMessage(
                    'session1',
                    [
                        {
                            type: EventType.FullSnapshot,
                            timestamp: 1000,
                            data: { source: 1 },
                        },
                    ],
                    { partition: 1 }
                ),
                createMessage(
                    'session2',
                    [
                        {
                            type: EventType.IncrementalSnapshot,
                            timestamp: 2000,
                            data: { source: 2 },
                        },
                    ],
                    { partition: 2 }
                ),
            ]

            messages.forEach((message) => recorder.record(message))
            recorder.discardPartition(1) // Discard partition 1

            const outputPromise = captureOutput(mockStream)
            await recorder.flush()

            const output = await outputPromise
            const lines = parseLines(output)

            // Should only contain message from partition 2
            expect(lines).toEqual([['window1', messages[1].message.eventsByWindowId.window1[0]]])
        })

        it('should correctly update size when discarding partitions', () => {
            const message1 = createMessage(
                'session1',
                [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                ],
                { partition: 1 }
            )
            const message2 = createMessage(
                'session2',
                [
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2 },
                    },
                ],
                { partition: 2 }
            )

            const size1 = recorder.record(message1)
            const size2 = recorder.record(message2)
            const totalSize = size1 + size2

            expect(recorder.size).toBe(totalSize)

            recorder.discardPartition(1)
            expect(recorder.size).toBe(size2)

            recorder.discardPartition(2)
            expect(recorder.size).toBe(0)
        })

        it('should handle discarding non-existent partitions', () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            const bytesWritten = recorder.record(message)
            expect(recorder.size).toBe(bytesWritten)

            // Should not throw or change size
            recorder.discardPartition(999)
            expect(recorder.size).toBe(bytesWritten)
        })
    })

    describe('metrics', () => {
        it('should increment metrics on flush', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2 },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 1500,
                        data: { href: 'https://example.com' },
                    },
                ]),
            ]

            messages.forEach((message) => recorder.record(message))
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(2) // Two sessions
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(3) // Three events total
        })

        it('should not increment metrics when no events are flushed', async () => {
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(0)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(0)
        })

        it('should not count events from discarded partitions', async () => {
            const messages = [
                createMessage(
                    'session1',
                    [
                        {
                            type: EventType.FullSnapshot,
                            timestamp: 1000,
                            data: { source: 1 },
                        },
                    ],
                    { partition: 1 }
                ),
                createMessage(
                    'session2',
                    [
                        {
                            type: EventType.IncrementalSnapshot,
                            timestamp: 2000,
                            data: { source: 2 },
                        },
                    ],
                    { partition: 2 }
                ),
            ]

            messages.forEach((message) => recorder.record(message))
            recorder.discardPartition(1)
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(1) // Only session from partition 2
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(1) // Only event from partition 2
        })

        it('should not count sessions again on subsequent flushes', async () => {
            const stream1 = new PassThrough()
            const stream2 = new PassThrough()
            const stream3 = new PassThrough()
            const finish1 = jest.fn().mockResolvedValue(undefined)
            const finish2 = jest.fn().mockResolvedValue(undefined)
            const finish3 = jest.fn().mockResolvedValue(undefined)

            mockWriter.open
                .mockResolvedValueOnce({ stream: stream1, finish: finish1 })
                .mockResolvedValueOnce({ stream: stream2, finish: finish2 })
                .mockResolvedValueOnce({ stream: stream3, finish: finish3 })

            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 1500,
                        data: { href: 'https://example.com' },
                    },
                ]),
            ]

            // First flush
            messages.forEach((message) => recorder.record(message))
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(2) // Two sessions
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(2) // Two events

            // Second flush without new messages
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(2)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(2)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(2)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(0) // No sessions
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(0) // No events

            // Add new message and flush again
            recorder.record(
                createMessage('session3', [
                    {
                        type: EventType.Custom,
                        timestamp: 2000,
                        data: { custom: 'data' },
                    },
                ])
            )
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(3)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(3)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(3)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(1) // Only the new session
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(1) // Only the new event
        })
    })
})
