import posthog from 'posthog-js'

import { EventType } from '@posthog/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource, SnapshotSourceType } from '~/types'

import { ViewportResolution } from './patch-meta-event'
import { ProcessingCache, processAllSnapshots } from './process-all-snapshots'
import { keyForSource } from './source-key'
import { clearThrottle } from './throttle-capturing'

describe('processAllSnapshots - inline meta patching', () => {
    const DEFAULT_VIEWPORT: ViewportResolution = {
        width: '1024',
        height: '768',
        href: 'https://blah.io',
    }
    const mockViewportForTimestamp = (): ViewportResolution => DEFAULT_VIEWPORT

    function createFullSnapshot(timestamp: number = 1000): RecordingSnapshot {
        return {
            type: EventType.FullSnapshot,
            timestamp,
            windowId: 'window1',
            data: {
                initialOffset: { top: 0, left: 0 },
                node: {
                    id: 1,
                    type: 2,
                    tagName: 'html',
                    attributes: {},
                    childNodes: [],
                },
            },
        }
    }

    function createMeta(
        width: number,
        height: number,
        timestamp: number = 1000,
        href: string = 'https://blah.io'
    ): RecordingSnapshot {
        return {
            type: EventType.Meta,
            timestamp,
            windowId: 'window1',
            data: {
                width,
                height,
                href,
            },
        }
    }

    function createIncrementalSnapshot(timestamp: number = 1500): RecordingSnapshot {
        return {
            type: EventType.IncrementalSnapshot,
            timestamp,
            windowId: 'window1',
            data: {},
        } as RecordingSnapshot
    }

    function createSource(
        sourceType: SnapshotSourceType = 'blob',
        blobKey: string = 'blob-key'
    ): SessionRecordingSnapshotSource {
        return {
            source: sourceType,
            start_timestamp: '2023-01-01T00:00:00Z',
            end_timestamp: '2023-01-01T01:00:00Z',
            blob_key: blobKey,
        }
    }

    function createSnapshotsBySource(
        source: SessionRecordingSnapshotSource,
        snapshots: RecordingSnapshot[]
    ): Record<string, { snapshots: RecordingSnapshot[] }> {
        const sourceKey = keyForSource(source)
        return {
            [sourceKey]: {
                snapshots,
            },
        }
    }

    function setupTest(
        snapshots: RecordingSnapshot[],
        source = createSource()
    ): {
        sources: SessionRecordingSnapshotSource[]
        snapshotsBySource: Record<string, { snapshots: RecordingSnapshot[] }>
        processingCache: ProcessingCache
    } {
        const sources = [source]
        const snapshotsBySource = createSnapshotsBySource(source, snapshots)
        const processingCache: ProcessingCache = {}
        return { sources, snapshotsBySource, processingCache }
    }

    const countByType = (result: RecordingSnapshot[], type: EventType): number =>
        result.filter((r) => r.type === type).length

    it('adds meta event before full snapshot when none exists', () => {
        const snapshots = [createFullSnapshot()]
        const { sources, snapshotsBySource, processingCache } = setupTest(snapshots)

        const result = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestamp,
            '12345'
        )

        expect(result).toHaveLength(2)
        expect(result[0].type).toBe(EventType.Meta)
        expect(result[0].data).toEqual({
            width: 1024,
            height: 768,
            href: 'https://blah.io',
        })
        expect(result[1].type).toBe(EventType.FullSnapshot)
    })

    it('does not add meta event if one already exists before full snapshot', () => {
        const snapshots = [createMeta(800, 600, 1000, 'http://test'), createFullSnapshot()]
        const { sources, snapshotsBySource, processingCache } = setupTest(snapshots)

        const result = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestamp,
            '12345'
        )

        expect(result).toHaveLength(2)
        expect(result[0].type).toBe(EventType.Meta)
        expect((result[0].data as any)?.width).toBe(800)
        expect(result[1].type).toBe(EventType.FullSnapshot)
    })

    it('handles multiple full snapshots correctly - each gets its own meta event', () => {
        const snapshots = [createFullSnapshot(1000), createIncrementalSnapshot(1500), createFullSnapshot(2000)]
        const { sources, snapshotsBySource, processingCache } = setupTest(snapshots)

        const result = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestamp,
            '12345'
        )

        expect(result).toHaveLength(5)
        expect(result[0].type).toBe(EventType.Meta)
        expect(result[0].timestamp).toBe(1000)
        expect(result[1].type).toBe(EventType.FullSnapshot)
        expect(result[1].timestamp).toBe(1000)

        expect(result[2].type).toBe(EventType.IncrementalSnapshot)

        expect(result[3].type).toBe(EventType.Meta)
        expect(result[3].timestamp).toBe(2000)
        expect(result[4].type).toBe(EventType.FullSnapshot)
        expect(result[4].timestamp).toBe(2000)
    })

    it('logs error when viewport dimensions are not available', () => {
        const mockViewportForTimestampNoData = (): ViewportResolution | undefined => undefined
        const snapshots = [createFullSnapshot()]
        const { sources, snapshotsBySource, processingCache } = setupTest(snapshots)

        jest.spyOn(posthog, 'captureException')

        const result = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestampNoData,
            '12345'
        )

        expect(posthog.captureException).toHaveBeenCalledWith(
            new Error('No event viewport or meta snapshot found for full snapshot'),
            expect.objectContaining({
                feature: 'session-recording-meta-patching',
                sessionRecordingId: '12345',
                sourceKey: 'blob-blob-key',
                throttleCaptureKey: '12345-no-viewport-found',
            })
        )
        expect(result).toHaveLength(1)
        expect(result[0].type).toBe(EventType.FullSnapshot)
    })

    it('does not log error twice for the same session', () => {
        clearThrottle()

        const mockViewportForTimestampNoData = (): ViewportResolution | undefined => undefined
        const source = createSource()
        const sources = [source]
        const snapshots = [createFullSnapshot()]
        const snapshotsBySource = createSnapshotsBySource(source, snapshots)
        const processingCache: ProcessingCache = {}

        jest.spyOn(posthog, 'captureException')

        expect(posthog.captureException).toHaveBeenCalledTimes(0)
        processAllSnapshots(sources, snapshotsBySource, processingCache, mockViewportForTimestampNoData, '12345')
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
        processAllSnapshots(sources, snapshotsBySource, {}, mockViewportForTimestampNoData, '12345')
        expect(posthog.captureException).toHaveBeenCalledTimes(1)
        processAllSnapshots(sources, snapshotsBySource, {}, mockViewportForTimestampNoData, '54321')
        expect(posthog.captureException).toHaveBeenCalledTimes(2)
    })

    it('caches snapshots with meta events included', () => {
        const snapshots = [createFullSnapshot()]
        const { sources, snapshotsBySource, processingCache } = setupTest(snapshots)

        // First call - should process and add meta event
        const result1 = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestamp,
            '12345'
        )

        expect(result1).toHaveLength(2)
        expect(result1[0].type).toBe(EventType.Meta)
        expect(result1[1].type).toBe(EventType.FullSnapshot)

        // Second call - should use cache and still include meta event
        const result2 = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestamp,
            '12345'
        )

        expect(result2).toHaveLength(2)
        expect(result2[0].type).toBe(EventType.Meta)
        expect(result2[1].type).toBe(EventType.FullSnapshot)

        // Cache should contain the processed snapshots with meta events
        const sourceKey = keyForSource(sources[0])
        expect(processingCache[sourceKey]).toHaveLength(2)
        expect(processingCache[sourceKey][0].type).toBe(EventType.Meta)
        expect(processingCache[sourceKey][1].type).toBe(EventType.FullSnapshot)

        // Verify no duplication by checking exact counts
        expect(countByType(result2, EventType.Meta)).toBe(1)
        expect(countByType(result2, EventType.FullSnapshot)).toBe(1)
    })

    it('handles multiple sources correctly', () => {
        const source1 = createSource('blob', 'blob-key-1')
        const source2 = createSource('blob', 'blob-key-2')
        const sources = [source1, source2]
        const snapshotsBySource = {
            ...createSnapshotsBySource(source1, [createFullSnapshot(1000)]),
            ...createSnapshotsBySource(source2, [createMeta(800, 600, 2000), createFullSnapshot(2000)]),
        }
        const processingCache: ProcessingCache = {}

        const result = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestamp,
            '12345'
        )

        expect(result).toHaveLength(4)
        // Results should be sorted by timestamp
        expect(result[0].type).toBe(EventType.Meta) // Added for source1
        expect(result[0].timestamp).toBe(1000)
        expect(result[1].type).toBe(EventType.FullSnapshot) // From source1
        expect(result[1].timestamp).toBe(1000)
        expect(result[2].type).toBe(EventType.Meta) // From source2
        expect(result[2].timestamp).toBe(2000)
        expect(result[3].type).toBe(EventType.FullSnapshot) // From source2
        expect(result[3].timestamp).toBe(2000)
    })

    it('does not patch meta event when previous source ends with meta and next starts with full snapshot', () => {
        const source1 = createSource('blob', 'blob-key-1')
        const source2 = createSource('blob', 'blob-key-2')
        const sources = [source1, source2]
        const snapshotsBySource = {
            ...createSnapshotsBySource(source1, [
                createFullSnapshot(1000),
                createMeta(1024, 768, 1500), // Source1 ends with meta
            ]),
            ...createSnapshotsBySource(source2, [
                createFullSnapshot(2000), // Source2 starts with full snapshot
            ]),
        }
        const processingCache: ProcessingCache = {}

        const result = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestamp,
            '12345'
        )

        expect(result).toHaveLength(4)
        // Results should be sorted by timestamp
        expect(result[0].type).toBe(EventType.Meta) // Added for first full snapshot
        expect(result[0].timestamp).toBe(1000)
        expect(result[1].type).toBe(EventType.FullSnapshot) // From source1
        expect(result[1].timestamp).toBe(1000)
        expect(result[2].type).toBe(EventType.Meta) // From source1 (original)
        expect(result[2].timestamp).toBe(1500)
        expect(result[3].type).toBe(EventType.FullSnapshot) // From source2 - should NOT have meta added
        expect(result[3].timestamp).toBe(2000)

        // Should be exactly 4 events, no extra meta event added before the second source's full snapshot
        expect(countByType(result, EventType.Meta)).toBe(2)
        expect(countByType(result, EventType.FullSnapshot)).toBe(2)
    })

    it('patches meta event when previous source ends without meta and next starts with full snapshot', () => {
        const source1 = createSource('blob', 'blob-key-1')
        const source2 = createSource('blob', 'blob-key-2')
        const sources = [source1, source2]
        const snapshotsBySource = {
            ...createSnapshotsBySource(source1, [
                createFullSnapshot(1000),
                createIncrementalSnapshot(1500), // Source1 ends with incremental (no meta)
            ]),
            ...createSnapshotsBySource(source2, [
                createFullSnapshot(2000), // Source2 starts with full snapshot
            ]),
        }
        const processingCache: ProcessingCache = {}

        const result = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache,
            mockViewportForTimestamp,
            '12345'
        )

        expect(result).toHaveLength(5)
        // Results should be sorted by timestamp
        expect(result[0].type).toBe(EventType.Meta) // Added for first full snapshot
        expect(result[0].timestamp).toBe(1000)
        expect(result[1].type).toBe(EventType.FullSnapshot) // From source1
        expect(result[1].timestamp).toBe(1000)

        expect(result[2].type).toBe(EventType.IncrementalSnapshot) // From source1

        expect(result[3].type).toBe(EventType.Meta) // Added for second full snapshot (cross-source)
        expect(result[3].timestamp).toBe(2000)
        expect(result[4].type).toBe(EventType.FullSnapshot) // From source2
        expect(result[4].timestamp).toBe(2000)

        // Should have 2 meta events (both patched) and 2 full snapshots
        expect(countByType(result, EventType.Meta)).toBe(2)
        expect(countByType(result, EventType.FullSnapshot)).toBe(2)
    })

    it('handles same source processed multiple times with fresh cache correctly', () => {
        const snapshots = [createFullSnapshot()]
        const source = createSource()
        const sources = [source]
        const snapshotsBySource = createSnapshotsBySource(source, snapshots)

        // First call with fresh cache
        const processingCache1: ProcessingCache = {}
        const result1 = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache1,
            mockViewportForTimestamp,
            '12345'
        )

        // Second call with different fresh cache (simulating edge case)
        const processingCache2: ProcessingCache = {}
        const result2 = processAllSnapshots(
            sources,
            snapshotsBySource,
            processingCache2,
            mockViewportForTimestamp,
            '12345'
        )

        // Both results should be identical and not have duplicated events
        expect(result1).toHaveLength(2)
        expect(result2).toHaveLength(2)
        expect(countByType(result1, EventType.Meta)).toBe(1)
        expect(countByType(result1, EventType.FullSnapshot)).toBe(1)
        expect(countByType(result2, EventType.Meta)).toBe(1)
        expect(countByType(result2, EventType.FullSnapshot)).toBe(1)
    })
})
