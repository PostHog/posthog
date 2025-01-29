import { PassThrough } from 'stream'

import { ParsedMessageData } from '../kafka/types'
import { SessionRecorder } from './recorder'

// RRWeb event type constants
const enum EventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
}

describe('SessionRecorder', () => {
    let recorder: SessionRecorder

    beforeEach(() => {
        recorder = new SessionRecorder()
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

    const parseLines = (data: string): Array<[string, any]> => {
        return data
            .trim()
            .split('\n')
            .map((line) => JSON.parse(line))
    }

    describe('recordMessage', () => {
        it('should record events in JSONL format', async () => {
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

            const bytesWritten = recorder.recordMessage(message)

            const stream = new PassThrough()
            let streamData = ''
            stream.on('data', (chunk) => {
                streamData += chunk
            })

            const result = await recorder.write(stream)
            const lines = parseLines(streamData)

            expect(lines).toEqual([
                ['window1', events[0]],
                ['window1', events[1]],
            ])
            expect(bytesWritten).toBeGreaterThan(0)
            expect(result.eventCount).toBe(2)
            expect(result.bytesWritten).toBe(bytesWritten)
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

            const stream = new PassThrough()
            let streamData = ''
            stream.on('data', (chunk) => {
                streamData += chunk
            })

            const result = await recorder.write(stream)
            const lines = parseLines(streamData)

            expect(lines).toEqual([
                ['window1', events.window1[0]],
                ['window1', events.window1[1]],
                ['window2', events.window2[0]],
                ['window2', events.window2[1]],
            ])
            expect(result.eventCount).toBe(4)
            expect(result.bytesWritten).toBeGreaterThan(0)
        })

        it('should handle empty events array', async () => {
            const message = createMessage('window1', [])
            const bytesWritten = recorder.recordMessage(message)

            const stream = new PassThrough()
            let streamData = ''
            stream.on('data', (chunk) => {
                streamData += chunk
            })

            const result = await recorder.write(stream)
            expect(streamData).toBe('')
            expect(bytesWritten).toBe(0)
            expect(result.eventCount).toBe(0)
            expect(result.bytesWritten).toBe(0)
        })

        it('should correctly count bytes for multi-byte characters', async () => {
            let bytesWritten = 0

            const events1 = {
                window1: [{ type: EventType.Custom, timestamp: 1000, data: { message: 'Testowanie z jeżem 🦔' } }],
            }
            const message1: ParsedMessageData = {
                ...createMessage('', []),
                eventsByWindowId: events1,
            }
            bytesWritten += recorder.recordMessage(message1)

            const events2 = {
                window1: [
                    {
                        type: EventType.Custom,
                        timestamp: 1500,
                        data: { message: '🦔 What do you call a hedgehog in the desert? A cactus impersonator!' },
                    },
                ],
            }
            const message2: ParsedMessageData = {
                ...createMessage('', []),
                eventsByWindowId: events2,
            }
            bytesWritten += recorder.recordMessage(message2)

            const events3 = {
                window2: [
                    {
                        type: EventType.Custom,
                        timestamp: 2000,
                        data: { message: "🦔 What's a hedgehog's favorite exercise? Spike jumps!" },
                    },
                ],
            }
            const message3: ParsedMessageData = {
                ...createMessage('', []),
                eventsByWindowId: events3,
            }
            bytesWritten += recorder.recordMessage(message3)

            const stream = new PassThrough()
            let bytesReceived = 0
            stream.on('data', (chunk) => {
                bytesReceived += Buffer.byteLength(chunk)
            })

            const result = await recorder.write(stream)
            expect(bytesReceived).toBe(bytesWritten)
            expect(result.bytesWritten).toBe(bytesWritten)
            expect(result.eventCount).toBe(3)
        })
    })

    describe('write', () => {
        it('should ensure last line ends with newline', async () => {
            const events = [
                { type: EventType.FullSnapshot, timestamp: 1000, data: {} },
                { type: EventType.IncrementalSnapshot, timestamp: 2000, data: {} },
            ]
            const message = createMessage('window1', events)
            recorder.recordMessage(message)

            const stream = new PassThrough()
            let streamData = ''
            stream.on('data', (chunk) => {
                streamData += chunk
            })

            const result = await recorder.write(stream)
            expect(streamData.endsWith('\n')).toBe(true)
            expect(result.eventCount).toBe(2)
            expect(result.bytesWritten).toBeGreaterThan(0)
        })

        it('should handle backpressure', async () => {
            const events = Array.from({ length: 100 }, (_, i) => ({
                type: EventType.Custom,
                timestamp: i * 1000,
                data: { large: 'x'.repeat(1000) }, // Create large events
            }))
            const message = createMessage('window1', events)
            recorder.recordMessage(message)

            const stream = new PassThrough({ highWaterMark: 100 }) // Small buffer to trigger backpressure
            let bytesWrittenBeforeDrain = 0
            let drainOccurred = false

            stream.on('data', (chunk) => {
                if (!drainOccurred) {
                    bytesWrittenBeforeDrain += Buffer.byteLength(chunk)
                }
            })

            const writePromise = recorder.write(stream)

            // Wait a tick to allow some data to be written
            await new Promise((resolve) => process.nextTick(resolve))

            // Verify that not all data was written before drain
            expect(bytesWrittenBeforeDrain).toBeGreaterThan(0)
            expect(bytesWrittenBeforeDrain).toBeLessThan(100000)

            // Now let the stream drain
            drainOccurred = true
            stream.resume()

            const result = await writePromise
            expect(result.eventCount).toBe(100)
            expect(result.bytesWritten).toBeGreaterThan(100000) // Should be large due to the event size
            expect(result.bytesWritten).toBeGreaterThan(bytesWrittenBeforeDrain) // More data written after drain
        })
    })
})
