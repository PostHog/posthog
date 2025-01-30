import snappy from 'snappy'

import { ParsedMessageData } from '../kafka/types'
import { SnappySessionRecorder } from './snappy-session-recorder'

// RRWeb event type constants
const enum EventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
}

describe('SnappySessionRecorder', () => {
    let recorder: SnappySessionRecorder

    beforeEach(() => {
        recorder = new SnappySessionRecorder()
    })

    const createMessage = (windowId: string, events: any[]): ParsedMessageData => ({
        distinct_id: 'distinct_id',
        session_id: 'session_id',
        eventsByWindowId: {
            [windowId]: events,
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
    })

    const readSnappyBuffer = async (buffer: Buffer): Promise<any[]> => {
        const decompressed = await snappy.uncompress(buffer)
        return decompressed
            .toString()
            .trim()
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean)
            .map((line) => JSON.parse(line))
    }

    describe('recordMessage', () => {
        it('should record events in snappy-compressed JSONL format', async () => {
            const events = [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: {
                        source: 1,
                        adds: [{ parentId: 1, nextId: 2, node: { tag: 'div', attrs: { class: 'test' } } }],
                    },
                },
                {
                    type: EventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                },
            ]
            const message = createMessage('window1', events)

            const rawBytesWritten = recorder.recordMessage(message)
            expect(rawBytesWritten).toBeGreaterThan(0)

            const { buffer, eventCount } = await recorder.end()
            const lines = await readSnappyBuffer(buffer)

            expect(lines).toEqual([
                ['window1', events[0]],
                ['window1', events[1]],
            ])
            expect(eventCount).toBe(2)
        })

        it('should handle multiple windows with multiple events', async () => {
            const events = {
                window1: [
                    {
                        type: EventType.Meta,
                        timestamp: 1000,
                        data: { href: 'https://example.com', width: 1024, height: 768 },
                    },
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1500,
                        data: {
                            source: 1,
                            adds: [{ parentId: 1, nextId: null, node: { tag: 'h1', attrs: { id: 'title' } } }],
                        },
                    },
                ],
                window2: [
                    {
                        type: EventType.Custom,
                        timestamp: 2000,
                        data: { tag: 'user-interaction', payload: { type: 'click', target: '#submit-btn' } },
                    },
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2500,
                        data: { source: 3, mousemove: [{ x: 100, y: 200, id: 1 }] },
                    },
                ],
            }
            const message: ParsedMessageData = {
                ...createMessage('', []),
                eventsByWindowId: events,
            }

            recorder.recordMessage(message)
            const { buffer, eventCount } = await recorder.end()
            const lines = await readSnappyBuffer(buffer)

            expect(lines).toEqual([
                ['window1', events.window1[0]],
                ['window1', events.window1[1]],
                ['window2', events.window2[0]],
                ['window2', events.window2[1]],
            ])
            expect(eventCount).toBe(4)
        })

        it('should handle empty events array', async () => {
            const message = createMessage('window1', [])
            recorder.recordMessage(message)

            const { buffer, eventCount } = await recorder.end()
            const lines = await readSnappyBuffer(buffer)

            expect(lines).toEqual([])
            expect(eventCount).toBe(0)
        })

        it('should handle large amounts of data', async () => {
            const events = Array.from({ length: 10000 }, (_, i) => ({
                type: EventType.Custom,
                timestamp: i * 100,
                data: { value: 'x'.repeat(1000) },
            }))

            // Split events into 100 messages of 100 events each
            for (let i = 0; i < events.length; i += 100) {
                const messageEvents = events.slice(i, i + 100)
                const message = createMessage('window1', messageEvents)
                recorder.recordMessage(message)
            }

            const { buffer, eventCount } = await recorder.end()
            const lines = await readSnappyBuffer(buffer)

            expect(lines.length).toBe(10000)
            expect(eventCount).toBe(10000)

            // Verify first and last events
            expect(lines[0]).toEqual(['window1', events[0]])
            expect(lines[lines.length - 1]).toEqual(['window1', events[events.length - 1]])
        })

        it('should throw error when recording after end', async () => {
            const message = createMessage('window1', [{ type: EventType.Custom, timestamp: 1000, data: {} }])
            recorder.recordMessage(message)
            await recorder.end()

            expect(() => recorder.recordMessage(message)).toThrow('Cannot record message after end() has been called')
        })

        it('should throw error when calling end multiple times', async () => {
            const message = createMessage('window1', [{ type: EventType.Custom, timestamp: 1000, data: {} }])
            recorder.recordMessage(message)
            await recorder.end()

            await expect(recorder.end()).rejects.toThrow('end() has already been called')
        })
    })
})
