import { DateTime } from 'luxon'
import snappy from 'snappy'

import { parseJSON } from '../../../../utils/json-parse'
import { ParsedMessageData } from '../kafka/types'
import { RRWebEventType } from '../rrweb-types'
import { SnappySessionRecorder } from './snappy-session-recorder'

describe('SnappySessionRecorder', () => {
    let recorder: SnappySessionRecorder

    beforeEach(() => {
        recorder = new SnappySessionRecorder('test_session_id', 1, 'test_batch_id')
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

    const readSnappyBuffer = async (buffer: Buffer): Promise<string> => {
        const decompressed = await snappy.uncompress(buffer)
        return decompressed.toString()
    }

    const parseSnappyBuffer = async (buffer: Buffer): Promise<any[]> => {
        const decompressed = await snappy.uncompress(buffer)
        return decompressed
            .toString()
            .trim()
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean)
            .map((line) => parseJSON(line))
    }

    describe('recordMessage', () => {
        it('should record events in snappy-compressed JSONL format', async () => {
            const events = [
                {
                    type: RRWebEventType.FullSnapshot,
                    timestamp: 1000,
                    data: {
                        source: 1,
                        adds: [{ parentId: 1, nextId: 2, node: { tag: 'div', attrs: { class: 'test' } } }],
                    },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                },
            ]
            const message = createMessage('window1', events)

            const rawBytesWritten = recorder.recordMessage(message)
            expect(rawBytesWritten).toBeGreaterThan(0)

            const { buffer, eventCount } = await recorder.end()
            const lines = await parseSnappyBuffer(buffer)

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
                        type: RRWebEventType.Meta,
                        timestamp: 1000,
                        data: { href: 'https://example.com', width: 1024, height: 768 },
                    },
                    {
                        type: RRWebEventType.FullSnapshot,
                        timestamp: 1500,
                        data: {
                            source: 1,
                            adds: [{ parentId: 1, nextId: null, node: { tag: 'h1', attrs: { id: 'title' } } }],
                        },
                    },
                ],
                window2: [
                    {
                        type: RRWebEventType.Custom,
                        timestamp: 2000,
                        data: { tag: 'user-interaction', payload: { type: 'click', target: '#submit-btn' } },
                    },
                    {
                        type: RRWebEventType.IncrementalSnapshot,
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
            const lines = await parseSnappyBuffer(buffer)

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
            const lines = await parseSnappyBuffer(buffer)

            expect(lines).toEqual([])
            expect(eventCount).toBe(0)
        })

        it('should handle large amounts of data', async () => {
            const events = Array.from({ length: 10000 }, (_, i) => ({
                type: RRWebEventType.Custom,
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
            const lines = await parseSnappyBuffer(buffer)

            expect(lines.length).toBe(10000)
            expect(eventCount).toBe(10000)

            // Verify first and last events
            expect(lines[0]).toEqual(['window1', events[0]])
            expect(lines[lines.length - 1]).toEqual(['window1', events[events.length - 1]])
        })

        it('should throw error when recording after end', async () => {
            const message = createMessage('window1', [{ type: RRWebEventType.Custom, timestamp: 1000, data: {} }])
            recorder.recordMessage(message)
            await recorder.end()

            expect(() => recorder.recordMessage(message)).toThrow('Cannot record message after end() has been called')
        })

        it('should throw error when calling end multiple times', async () => {
            const message = createMessage('window1', [{ type: RRWebEventType.Custom, timestamp: 1000, data: {} }])
            recorder.recordMessage(message)
            await recorder.end()

            await expect(recorder.end()).rejects.toThrow('end() has already been called')
        })
    })

    describe('timestamps', () => {
        it('should track start and end timestamps from events range', async () => {
            const events = [
                {
                    type: RRWebEventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 2 },
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.startDateTime).toEqual(DateTime.fromMillis(1000))
            expect(result.endDateTime).toEqual(DateTime.fromMillis(2000))
        })

        it('should track min/max timestamps across multiple messages', async () => {
            const messages = [
                createMessage('window1', [
                    { type: RRWebEventType.Meta, timestamp: 2000 },
                    { type: RRWebEventType.FullSnapshot, timestamp: 3000 },
                ]),
                createMessage('window2', [
                    { type: RRWebEventType.FullSnapshot, timestamp: 1000 },
                    { type: RRWebEventType.IncrementalSnapshot, timestamp: 4000 },
                ]),
            ]

            messages.forEach((message) => recorder.recordMessage(message))
            const result = await recorder.end()

            expect(result.startDateTime).toEqual(DateTime.fromMillis(1000)) // Min from all messages
            expect(result.endDateTime).toEqual(DateTime.fromMillis(4000)) // Max from all messages
        })

        it('should handle empty events array', async () => {
            const message = createMessage('window1', [])
            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.startDateTime).toEqual(DateTime.fromMillis(0))
            expect(result.endDateTime).toEqual(DateTime.fromMillis(0))
        })
    })

    describe('metadata', () => {
        it('should return empty metadata', async () => {
            const result = await recorder.end()

            expect(result.firstUrl).toBeNull()
            expect(result.urls).toEqual([])
            expect(result.clickCount).toBe(0)
            expect(result.keypressCount).toBe(0)
            expect(result.mouseActivityCount).toBe(0)
            expect(result.activeMilliseconds).toBe(0)
            expect(result.size).toBe(0)
            expect(result.messageCount).toBe(0)
            expect(result.snapshotSource).toBeNull()
            expect(result.snapshotLibrary).toBeNull()
        })
    })

    describe('distinctId', () => {
        it('should throw error when accessing distinctId before recording any messages', () => {
            expect(() => recorder.distinctId).toThrow('No distinct_id set. No messages recorded yet.')
        })

        it('should store distinctId from first message', () => {
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])
            recorder.recordMessage(message)

            expect(recorder.distinctId).toBe('distinct_id')
        })

        it('should keep first message distinctId even if later messages have different distinctId', () => {
            recorder.recordMessage(
                createMessage('window1', [
                    {
                        type: RRWebEventType.Meta,
                        timestamp: 1000,
                        data: {},
                    },
                ])
            )

            const message2 = {
                ...createMessage('window1', [
                    {
                        type: RRWebEventType.Meta,
                        timestamp: 2000,
                        data: {},
                    },
                ]),
                distinct_id: 'different_distinct_id',
            }
            recorder.recordMessage(message2)

            expect(recorder.distinctId).toBe('distinct_id')
        })

        it('should maintain distinctId after end() is called', async () => {
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])
            recorder.recordMessage(message)
            await recorder.end()

            expect(recorder.distinctId).toBe('distinct_id')
        })
    })

    describe('URL accumulation', () => {
        it('should accumulate URLs from a single message', async () => {
            const events = [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: 'https://example.com' },
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.firstUrl).toBe('https://example.com')
            expect(result.urls).toEqual(['https://example.com'])
        })

        it('should limit URL length to 4KB', async () => {
            // Create a URL that exceeds the 4KB limit
            const longUrl = 'https://example.com/' + 'a'.repeat(5000)

            const events = [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: longUrl },
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            // URL should be truncated to 4KB (4096 characters)
            expect(result.firstUrl?.length).toBe(4096)
            expect(result.urls?.[0].length).toBe(4096)
        })

        it('should limit the number of URLs to 25', async () => {
            // Create 30 different URLs
            const events = Array.from({ length: 30 }, (_, i) => ({
                type: RRWebEventType.Meta,
                timestamp: 1000 + i * 100,
                data: { href: `https://example${i}.com` },
            }))

            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            // Only the first 25 URLs should be stored
            expect(result.urls?.length).toBe(25)
            // First URL should be the first one in the events array
            expect(result.firstUrl).toBe('https://example0.com')
        })

        it('should accumulate URLs from multiple messages', async () => {
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: 'https://example1.com' },
                },
            ])
            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2000,
                    data: { href: 'https://example2.com' },
                },
            ])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.firstUrl).toBe('https://example1.com')
            expect(result.urls).toEqual(['https://example1.com', 'https://example2.com'])
        })

        it('should not overwrite first URL with subsequent messages', async () => {
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: 'https://first-url.com' },
                },
            ])
            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2000,
                    data: { href: 'https://second-url.com' },
                },
            ])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.firstUrl).toBe('https://first-url.com')
            expect(result.urls).toEqual(['https://first-url.com', 'https://second-url.com'])
        })

        it('should handle a message without URLs followed by one with URLs', async () => {
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])
            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2000,
                    data: { href: 'https://example.com' },
                },
            ])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.firstUrl).toBe('https://example.com')
            expect(result.urls).toEqual(['https://example.com'])
        })

        it('should handle messages with no URLs at all', async () => {
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.firstUrl).toBeNull()
            expect(result.urls).toEqual([])
        })

        it('should accumulate URLs from multiple events within a single message', async () => {
            const events = [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: 'https://example1.com' },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1500,
                    data: { href: 'https://example2.com' },
                },
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2000,
                    data: { href: 'https://example3.com' },
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.firstUrl).toBe('https://example1.com')
            expect(result.urls).toEqual(['https://example1.com', 'https://example2.com', 'https://example3.com'])
        })
    })

    describe('Click counting', () => {
        it('should count single click events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 2, type: 2 }, // MouseInteraction, Click
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.clickCount).toBe(1)
        })

        it('should count multiple click events in a single message', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 2, type: 2 }, // MouseInteraction, Click
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 2, type: 4 }, // MouseInteraction, DblClick
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.clickCount).toBe(2)
        })

        it('should count click events across multiple messages', async () => {
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 2, type: 2 }, // MouseInteraction, Click
                },
            ])
            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 2, type: 3 }, // MouseInteraction, ContextMenu
                },
            ])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.clickCount).toBe(2)
        })

        it('should not count non-click events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 2, type: 0 }, // MouseInteraction, MouseUp
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 2, type: 1 }, // MouseInteraction, MouseDown
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.clickCount).toBe(0)
        })

        it('should handle mixed click and non-click events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 2, type: 2 }, // MouseInteraction, Click
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 2, type: 0 }, // MouseInteraction, MouseUp
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 2, type: 4 }, // MouseInteraction, DblClick
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.clickCount).toBe(2)
        })
    })

    describe('Keypress counting', () => {
        it('should count single keypress events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 5 }, // Input
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.keypressCount).toBe(1)
        })

        it('should count multiple keypress events in a single message', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 5 }, // Input
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 5 }, // Input
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.keypressCount).toBe(2)
        })

        it('should count keypress events across multiple messages', async () => {
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 5 }, // Input
                },
            ])
            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 5 }, // Input
                },
            ])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.keypressCount).toBe(2)
        })

        it('should not count non-keypress events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 2 }, // MouseInteraction
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 3 }, // Scroll
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.keypressCount).toBe(0)
        })

        it('should handle mixed keypress and non-keypress events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 5 }, // Input
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 2 }, // MouseInteraction
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 5 }, // Input
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.keypressCount).toBe(2)
        })
    })

    describe('Mouse activity counting', () => {
        it('should count single mouse activity events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 1 }, // MouseMove
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.mouseActivityCount).toBe(1)
        })

        it('should count multiple mouse activity events in a single message', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 1 }, // MouseMove
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 6 }, // TouchMove
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.mouseActivityCount).toBe(2)
        })

        it('should count mouse activity events across multiple messages', async () => {
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 1 }, // MouseMove
                },
            ])
            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 6 }, // TouchMove
                },
            ])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.mouseActivityCount).toBe(2)
        })

        it('should not count non-mouse activity events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 3 }, // Scroll - not mouse activity
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 4 }, // ViewportResize - not mouse activity
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 5 }, // Input - not mouse activity
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.mouseActivityCount).toBe(0)
        })

        it('should handle mixed mouse and non-mouse activity events', async () => {
            const events = [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1000,
                    data: { source: 1 }, // MouseMove - counts as mouse activity
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 1500,
                    data: { source: 3 }, // Scroll - not mouse activity
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 6 }, // TouchMove - counts as mouse activity
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2500,
                    data: { source: 4 }, // ViewportResize - not mouse activity
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 3000,
                    data: { source: 5 }, // Input - not mouse activity
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            // Only MouseMove and TouchMove should be counted
            expect(result.mouseActivityCount).toBe(2)
        })
    })

    describe('Message counting', () => {
        it('should count a single message', async () => {
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.messageCount).toBe(1)
        })

        it('should count multiple messages', async () => {
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])
            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2000,
                    data: {},
                },
            ])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.messageCount).toBe(2)
        })

        it('should count zero messages when none are recorded', async () => {
            const result = await recorder.end()

            expect(result.messageCount).toBe(0)
        })
    })

    describe('Snapshot source and library tracking', () => {
        it('should set default values when no snapshot source or library is provided', async () => {
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])

            // Message already has null values for snapshot_source and snapshot_library

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.snapshotSource).toBe('web') // Default value for source
            expect(result.snapshotLibrary).toBeNull() // Default value for library
        })

        it('should set snapshot source and library from message', async () => {
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])

            message.snapshot_source = 'mobile'
            message.snapshot_library = 'posthog-android'

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.snapshotSource).toBe('mobile')
            expect(result.snapshotLibrary).toBe('posthog-android')
        })

        it('should limit snapshot source and library fields to 1000 characters', async () => {
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])

            const longString = 'a'.repeat(2000)
            message.snapshot_source = longString
            message.snapshot_library = longString

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.snapshotSource).toBe('a'.repeat(1000))
            expect(result.snapshotLibrary).toBe('a'.repeat(1000))
        })

        it('should use values from first message when multiple messages have different values', async () => {
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])

            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 2000,
                    data: {},
                },
            ])

            message1.snapshot_source = 'web'
            message1.snapshot_library = 'posthog-js'

            message2.snapshot_source = 'mobile'
            message2.snapshot_library = 'posthog-android'

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.snapshotSource).toBe('web')
            expect(result.snapshotLibrary).toBe('posthog-js')
        })

        it('should use "web" as default for snapshot source if not provided', async () => {
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])

            // Keep snapshot_source as null and set library
            message.snapshot_library = 'posthog-js'

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.snapshotSource).toBe('web')
            expect(result.snapshotLibrary).toBe('posthog-js')
        })
    })

    describe('Buffer size reporting', () => {
        it('should report the uncompressed buffer size', async () => {
            // Create a message with a known event
            const events = [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: 'https://example.com' },
                },
            ]

            const message = createMessage('window1', events)
            recorder.recordMessage(message)
            const result = await recorder.end()

            const decompressedBuffer = await readSnappyBuffer(result.buffer)
            expect(result.size).toBe(decompressedBuffer.length)
        })
    })

    describe('Batch ID', () => {
        it('should include batch ID in end result', async () => {
            const batchId = 'test-batch-123'
            const recorder = new SnappySessionRecorder('test_session_id', 1, batchId)
            const message = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: {},
                },
            ])

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.batchId).toBe(batchId)
        })

        it('should maintain batch ID across multiple messages', async () => {
            const batchId = 'test-batch-456'
            const recorder = new SnappySessionRecorder('test_session_id', 1, batchId)

            const message1 = createMessage('window1', [{ type: RRWebEventType.Meta, timestamp: 1000, data: {} }])
            const message2 = createMessage('window2', [{ type: RRWebEventType.Meta, timestamp: 2000, data: {} }])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            expect(result.batchId).toBe(batchId)
        })

        it('should include batch ID even with no messages', async () => {
            const batchId = 'test-batch-789'
            const recorder = new SnappySessionRecorder('test_session_id', 1, batchId)
            const result = await recorder.end()

            expect(result.batchId).toBe(batchId)
        })
    })

    describe('Active time calculation', () => {
        it('should calculate active time from events', async () => {
            // Create events with timestamps that would result in active time
            const events = [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: 'https://example.com' },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000, // 1 second after first event
                    data: { source: 1 }, // MouseMove - active event
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 3000, // 1 second after second event
                    data: { source: 2, type: 2 }, // MouseInteraction, Click - active event
                },
            ]
            const message = createMessage('window1', events)

            recorder.recordMessage(message)
            const result = await recorder.end()

            expect(result.activeMilliseconds).toEqual(1000)
        })

        it('should handle multiple windows when calculating active time', async () => {
            // Create events for first window
            const message1 = createMessage('window1', [
                {
                    type: RRWebEventType.Meta,
                    timestamp: 1000,
                    data: { href: 'https://example.com' },
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 1 }, // MouseMove - active event
                },
            ])

            // Create events for second window
            const message2 = createMessage('window2', [
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 3000,
                    data: { source: 2, type: 2 }, // MouseInteraction, Click - active event
                },
                {
                    type: RRWebEventType.IncrementalSnapshot,
                    timestamp: 4000,
                    data: { source: 5 }, // Input - active event
                },
            ])

            recorder.recordMessage(message1)
            recorder.recordMessage(message2)
            const result = await recorder.end()

            // The active time should be calculated based on events from both windows
            expect(result.activeMilliseconds).toEqual(2000)
        })
    })
})
