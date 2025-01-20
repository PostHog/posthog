import { PassThrough } from 'stream'

import {
    SessionBatchFlusher,
    SessionBatchRecorder,
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

describe('SessionBatchRecorder', () => {
    let recorder: SessionBatchRecorder
    let mockFlusher: jest.Mocked<SessionBatchFlusher>
    let mockStream: PassThrough

    beforeEach(() => {
        mockStream = new PassThrough()
        mockFlusher = {
            open: jest.fn().mockResolvedValue(mockStream),
            finish: jest.fn().mockResolvedValue(undefined),
        }
        recorder = new SessionBatchRecorder(mockFlusher)
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

    const parseLines = (data: string): Array<[string, RRWebEvent]> => {
        return data
            .trim()
            .split('\n')
            .map((line) => JSON.parse(line))
    }

    const captureOutput = (): Promise<string> => {
        return new Promise<string>((resolve) => {
            let streamData = ''
            mockStream.on('data', (chunk) => {
                streamData += chunk
            })
            mockStream.on('end', () => {
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
            const outputPromise = captureOutput()
            await recorder.flush()

            expect(mockFlusher.open).toHaveBeenCalled()
            expect(mockFlusher.finish).toHaveBeenCalled()

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
            const outputPromise = captureOutput()
            await recorder.flush()

            expect(mockFlusher.open).toHaveBeenCalled()
            expect(mockFlusher.finish).toHaveBeenCalled()

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
            const outputPromise = captureOutput()
            await recorder.flush()

            expect(mockFlusher.open).toHaveBeenCalled()
            expect(mockFlusher.finish).toHaveBeenCalled()

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

            const outputPromise = captureOutput()
            await recorder.flush()

            expect(mockFlusher.open).toHaveBeenCalled()
            expect(mockFlusher.finish).toHaveBeenCalled()

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

            // Record events in interleaved order
            messages.forEach((message) => recorder.record(message))
            const outputPromise = captureOutput()
            await recorder.flush()

            expect(mockFlusher.open).toHaveBeenCalled()
            expect(mockFlusher.finish).toHaveBeenCalled()

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
})
