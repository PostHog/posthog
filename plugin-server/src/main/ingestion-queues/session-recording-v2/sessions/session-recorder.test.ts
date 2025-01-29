import { PassThrough } from 'stream'
import { createGunzip } from 'zlib'

import { ParsedMessageData } from '../kafka/types'
import { SessionRecorder } from './session-recorder'

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

    const readGzippedStream = async (stream: PassThrough): Promise<string[]> => {
        return new Promise((resolve, reject) => {
            const gunzip = createGunzip()
            const chunks: Buffer[] = []

            // Handle errors from both streams
            stream.on('error', (error) => {
                gunzip.destroy()
                reject(new Error(`Error in source stream: ${error.message}`))
            })

            gunzip.on('error', (error) => {
                stream.destroy()
                reject(new Error(`Error decompressing data: ${error.message}`))
            })

            // Handle data
            gunzip.on('data', (chunk) => {
                chunks.push(chunk)
            })

            // Handle completion
            gunzip.on('end', () => {
                try {
                    const result = Buffer.concat(chunks as any)
                        .toString()
                        .trim()
                        .split('\n')
                        .map((line) => line.trim())
                        .filter(Boolean)
                        .map((line) => JSON.parse(line))
                    resolve(result)
                } catch (error) {
                    reject(new Error(`Failed to process stream data: ${error.message}`))
                } finally {
                    stream.destroy()
                    gunzip.destroy()
                }
            })

            // Pipe the streams
            stream.pipe(gunzip)
        })
    }

    describe('recordMessage', () => {
        it('should record events in gzipped JSONL format', async () => {
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

            const stream = new PassThrough()
            const { stream: gzipStream, eventCount } = recorder.end()
            gzipStream.pipe(stream)
            const lines = await readGzippedStream(stream)

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

            const stream = new PassThrough()
            const { stream: gzipStream, eventCount } = recorder.end()
            gzipStream.pipe(stream)
            const lines = await readGzippedStream(stream)

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

            const stream = new PassThrough()
            const { stream: gzipStream, eventCount } = recorder.end()
            gzipStream.pipe(stream)
            const lines = await readGzippedStream(stream)

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

            const stream = new PassThrough()
            const { stream: gzipStream, eventCount } = recorder.end()
            gzipStream.pipe(stream)
            const lines = await readGzippedStream(stream)

            expect(lines.length).toBe(10000)
            expect(eventCount).toBe(10000)

            // Verify first and last events
            expect(lines[0]).toEqual(['window1', events[0]])
            expect(lines[lines.length - 1]).toEqual(['window1', events[events.length - 1]])
        })
    })
})
