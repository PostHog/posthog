import { PassThrough } from 'stream'

import { ParsedMessageData } from '../../../../../src/main/ingestion-queues/session-recording-v2/kafka/types'
import { SessionRecorder } from '../../../../../src/main/ingestion-queues/session-recording-v2/sessions/recorder'

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
        it('should record events in JSONL format', () => {
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

            recorder.dump(stream)
            const lines = parseLines(streamData)

            expect(lines).toEqual([
                ['window1', events[0]],
                ['window1', events[1]],
            ])
            expect(bytesWritten).toBeGreaterThan(0)
        })

        it('should handle multiple windows with multiple events', () => {
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

            recorder.dump(stream)
            const lines = parseLines(streamData)

            expect(lines).toEqual([
                ['window1', events.window1[0]],
                ['window1', events.window1[1]],
                ['window2', events.window2[0]],
                ['window2', events.window2[1]],
            ])
        })

        it('should handle empty events array', () => {
            const message = createMessage('window1', [])
            const bytesWritten = recorder.recordMessage(message)

            const stream = new PassThrough()
            let streamData = ''
            stream.on('data', (chunk) => {
                streamData += chunk
            })

            recorder.dump(stream)
            expect(streamData).toBe('')
            expect(bytesWritten).toBe(0)
        })

        it('should correctly count bytes for multi-byte characters', () => {
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

            recorder.dump(stream)

            expect(bytesReceived).toBe(bytesWritten)
        })
    })

    describe('dump', () => {
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

            await recorder.dump(stream)
            expect(streamData.endsWith('\n')).toBe(true)
        })
    })
})
