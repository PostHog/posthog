import { DateTime } from 'luxon'
import snappy from 'snappy'

import { SerializedSessionData, SnappySessionRecorder } from './snappy-session-recorder'

describe('SnappySessionRecorder', () => {
    let recorder: SnappySessionRecorder

    beforeEach(() => {
        recorder = new SnappySessionRecorder('test_session_id', 1, 'test_batch_id')
    })

    const chunk = (windowId: string, event: object): Buffer => Buffer.from(JSON.stringify([windowId, event]) + '\n')

    // Per-message data as the extract-session-data step produces it; the recorder only aggregates.
    const createData = (overrides: Partial<SerializedSessionData> = {}): SerializedSessionData => {
        const chunks = overrides.chunks ?? [chunk('window1', { type: 3, timestamp: 1000 })]
        return {
            chunks,
            rawBytes: chunks.reduce((sum, c) => sum + c.length, 0),
            eventCount: chunks.length,
            segmentationEvents: [],
            urls: [],
            clickCount: 0,
            keypressCount: 0,
            mouseActivityCount: 0,
            eventsRange: {
                start: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                end: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
            },
            distinctId: 'distinct_id',
            snapshotSource: 'web',
            snapshotLibrary: null,
            ...overrides,
        }
    }

    const readSnappyBuffer = async (buffer: Buffer): Promise<string> => {
        const decompressed = await snappy.uncompress(buffer)
        return decompressed.toString()
    }

    describe('chunk aggregation', () => {
        it('appends chunks across messages and compresses them in order', async () => {
            const chunks1 = [
                chunk('window1', { type: 2, timestamp: 1000 }),
                chunk('window1', { type: 3, timestamp: 2000 }),
            ]
            const chunks2 = [chunk('window2', { type: 3, timestamp: 3000 })]

            const bytes1 = recorder.recordSessionData(createData({ chunks: chunks1 }))
            const bytes2 = recorder.recordSessionData(createData({ chunks: chunks2 }))
            const result = await recorder.end()

            expect(bytes1).toBe(chunks1[0].length + chunks1[1].length)
            expect(bytes2).toBe(chunks2[0].length)
            expect(await readSnappyBuffer(result.buffer)).toBe(Buffer.concat([...chunks1, ...chunks2]).toString())
            expect(result.eventCount).toBe(3)
            expect(result.messageCount).toBe(2)
            expect(result.size).toBe(bytes1 + bytes2)
        })

        it('sums the activity counts across messages', async () => {
            recorder.recordSessionData(createData({ clickCount: 2, keypressCount: 1, mouseActivityCount: 3 }))
            recorder.recordSessionData(createData({ clickCount: 1, keypressCount: 4, mouseActivityCount: 2 }))

            const result = await recorder.end()

            expect(result.clickCount).toBe(3)
            expect(result.keypressCount).toBe(5)
            expect(result.mouseActivityCount).toBe(5)
        })

        it('computes active time from the accumulated segmentation events', async () => {
            const t0 = DateTime.fromISO('2025-01-01T01:00:00Z').toMillis()
            recorder.recordSessionData(
                createData({
                    segmentationEvents: [
                        { timestamp: t0, isActive: true },
                        { timestamp: t0 + 1000, isActive: true },
                    ],
                })
            )

            const result = await recorder.end()

            expect(result.activeMilliseconds).toBe(1000)
        })
    })

    describe('timestamps', () => {
        it('tracks min and max timestamps across messages', async () => {
            recorder.recordSessionData(
                createData({
                    eventsRange: {
                        start: DateTime.fromISO('2025-01-01T01:00:01.000Z'),
                        end: DateTime.fromISO('2025-01-01T01:00:02.000Z'),
                    },
                })
            )
            recorder.recordSessionData(
                createData({
                    eventsRange: {
                        start: DateTime.fromISO('2025-01-01T01:00:00.000Z'),
                        end: DateTime.fromISO('2025-01-01T01:00:03.000Z'),
                    },
                })
            )

            const result = await recorder.end()

            expect(result.startDateTime).toEqual(DateTime.fromISO('2025-01-01T01:00:00.000Z'))
            expect(result.endDateTime).toEqual(DateTime.fromISO('2025-01-01T01:00:03.000Z'))
        })
    })

    describe('first-writer-wins fields', () => {
        it('keeps the first distinct id, snapshot source, and library', async () => {
            recorder.recordSessionData(
                createData({ distinctId: 'first_user', snapshotSource: 'web', snapshotLibrary: 'posthog-js' })
            )
            recorder.recordSessionData(
                createData({ distinctId: 'other_user', snapshotSource: 'mobile', snapshotLibrary: 'posthog-android' })
            )

            const result = await recorder.end()

            expect(recorder.distinctId).toBe('first_user')
            expect(result.snapshotSource).toBe('web')
            expect(result.snapshotLibrary).toBe('posthog-js')
        })

        it('throws when accessing distinctId before recording any data', () => {
            expect(() => recorder.distinctId).toThrow('No distinct_id set. No messages recorded yet.')
        })

        it('maintains distinctId after end() is called', async () => {
            recorder.recordSessionData(createData())
            await recorder.end()

            expect(recorder.distinctId).toBe('distinct_id')
        })
    })

    describe('url aggregation', () => {
        it('dedupes urls and keeps the first as firstUrl', async () => {
            recorder.recordSessionData(createData({ urls: ['https://first.com', 'https://second.com'] }))
            recorder.recordSessionData(createData({ urls: ['https://first.com', 'https://third.com'] }))

            const result = await recorder.end()

            expect(result.firstUrl).toBe('https://first.com')
            expect(result.urls).toEqual(['https://first.com', 'https://second.com', 'https://third.com'])
        })

        it('truncates urls to 4KB', async () => {
            const longUrl = 'https://example.com/' + 'a'.repeat(5000)
            recorder.recordSessionData(createData({ urls: [longUrl] }))

            const result = await recorder.end()

            expect(result.firstUrl?.length).toBe(4096)
            expect(result.urls?.[0].length).toBe(4096)
        })

        it('caps the number of urls at 25', async () => {
            const urls = Array.from({ length: 30 }, (_, i) => `https://example${i}.com`)
            recorder.recordSessionData(createData({ urls }))

            const result = await recorder.end()

            expect(result.urls?.length).toBe(25)
            expect(result.firstUrl).toBe('https://example0.com')
        })

        it('reports no urls when none were recorded', async () => {
            recorder.recordSessionData(createData())

            const result = await recorder.end()

            expect(result.firstUrl).toBeNull()
            expect(result.urls).toEqual([])
        })
    })

    describe('lifecycle', () => {
        it('returns empty metadata when nothing was recorded', async () => {
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
            expect(result.startDateTime).toEqual(DateTime.fromMillis(0))
            expect(result.endDateTime).toEqual(DateTime.fromMillis(0))
        })

        it('throws when recording after end', async () => {
            recorder.recordSessionData(createData())
            await recorder.end()

            expect(() => recorder.recordSessionData(createData())).toThrow(
                'Cannot record message after end() has been called'
            )
        })

        it('throws when calling end multiple times', async () => {
            recorder.recordSessionData(createData())
            await recorder.end()

            await expect(recorder.end()).rejects.toThrow('end() has already been called')
        })

        it('includes the batch id in the end result', async () => {
            const result = await recorder.end()

            expect(result.batchId).toBe('test_batch_id')
        })
    })
})
