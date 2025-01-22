import { PassThrough } from 'stream'

import {
    BaseSessionBatchRecorder,
    SessionBatchFlusher,
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

describe('BaseSessionBatchRecorder', () => {
    let recorder: BaseSessionBatchRecorder
    let mockFlusher: jest.Mocked<SessionBatchFlusher>
    let mockStream: PassThrough
    let mockFinish: () => Promise<void>

    beforeEach(() => {
        mockStream = new PassThrough()
        mockFinish = jest.fn().mockResolvedValue(undefined)
        mockFlusher = {
            open: jest.fn().mockImplementation(() =>
                Promise.resolve({
                    stream: mockStream,
                    finish: mockFinish,
                })
            ),
        }
        recorder = new BaseSessionBatchRecorder(mockFlusher)
    })

    const createMessage = (sessionId: string, events: RRWebEvent[]): MessageWithTeam => ({
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

    describe('recording and flushing', () => {
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

            expect(mockFlusher.open).toHaveBeenCalled()
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

            expect(mockFlusher.open).toHaveBeenCalled()
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

            expect(mockFlusher.open).toHaveBeenCalled()
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

            expect(mockFlusher.open).toHaveBeenCalled()
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

            expect(mockFlusher.open).toHaveBeenCalled()
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

            mockFlusher.open
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

            expect(mockFlusher.open).toHaveBeenCalledTimes(1)
            expect(finish1).toHaveBeenCalledTimes(1)
            expect(finish2).not.toHaveBeenCalled()
            const output1 = await outputPromise1

            // Record another message after flush
            recorder.record(message2)
            const outputPromise2 = captureOutput(stream2)
            await recorder.flush()

            expect(mockFlusher.open).toHaveBeenCalledTimes(2)
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

            mockFlusher.open
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
            expect(mockFlusher.open).toHaveBeenCalledTimes(1)
            expect(finish1).toHaveBeenCalledTimes(1)
            expect(finish2).not.toHaveBeenCalled()

            const outputPromise = captureOutput(stream2)
            await recorder.flush()
            const output = await outputPromise

            expect(output).toBe('')
            expect(mockFlusher.open).toHaveBeenCalledTimes(2)
            expect(finish1).toHaveBeenCalledTimes(1)
            expect(finish2).toHaveBeenCalledTimes(1)
        })
    })
})
