import { EventType } from '@posthog/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { SnapshotStore } from './SnapshotStore'

function makeSource(
    index: number,
    startMin: number = index,
    endMin: number = index + 1
): SessionRecordingSnapshotSource {
    return {
        source: 'blob_v2',
        blob_key: String(index),
        start_timestamp: new Date(Date.UTC(2023, 7, 11, 12, startMin, 0)).toISOString(),
        end_timestamp: new Date(Date.UTC(2023, 7, 11, 12, endMin, 0)).toISOString(),
    }
}

function makeSources(count: number): SessionRecordingSnapshotSource[] {
    return Array.from({ length: count }, (_, i) => makeSource(i))
}

function makeSnapshot(
    timestamp: number,
    windowId: number = 1,
    type: EventType = EventType.IncrementalSnapshot
): RecordingSnapshot {
    return { timestamp, windowId, type, data: {} } as unknown as RecordingSnapshot
}

function makeFullSnapshot(timestamp: number, windowId: number = 1): RecordingSnapshot {
    return {
        timestamp,
        windowId,
        type: EventType.FullSnapshot,
        data: { node: {}, initialOffset: { top: 0, left: 0 } },
    } as unknown as RecordingSnapshot
}

describe('SnapshotStore', () => {
    describe('setSources', () => {
        it.each([
            { count: 0, expectedCount: 0 },
            { count: 5, expectedCount: 5 },
            { count: 100, expectedCount: 100 },
        ])('creates $expectedCount entries from $count sources', ({ count, expectedCount }) => {
            const store = new SnapshotStore()
            store.setSources(makeSources(count))
            expect(store.sourceCount).toBe(expectedCount)
        })

        it('entries start as unloaded', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            for (let i = 0; i < 3; i++) {
                expect(store.getEntry(i)?.state).toBe('unloaded')
            }
        })

        it('parses timestamps to ms', () => {
            const store = new SnapshotStore()
            store.setSources([makeSource(0, 5, 10)])
            const entry = store.getEntry(0)!
            expect(entry.startMs).toBe(new Date(Date.UTC(2023, 7, 11, 12, 5, 0)).getTime())
            expect(entry.endMs).toBe(new Date(Date.UTC(2023, 7, 11, 12, 10, 0)).getTime())
        })

        it('bumps version', () => {
            const store = new SnapshotStore()
            const v0 = store.version
            store.setSources(makeSources(1))
            expect(store.version).toBeGreaterThan(v0)
        })
    })

    describe('markLoaded', () => {
        it('marks source as loaded and extracts FullSnapshot timestamps', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const ts = new Date(Date.UTC(2023, 7, 11, 12, 1, 30)).getTime()
            const snaps = [makeFullSnapshot(ts), makeSnapshot(ts + 100)]
            store.markLoaded(1, snaps)

            expect(store.getEntry(1)?.state).toBe('loaded')
            expect(store.getEntry(0)?.state).toBe('unloaded')
            expect(store.getEntry(1)?.fullSnapshotTimestamps).toEqual([ts])
        })

        it('extracts Meta timestamps', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(1))

            const ts = 1000
            const metaSnap = {
                timestamp: ts,
                windowId: 1,
                type: EventType.Meta,
                data: {},
            } as unknown as RecordingSnapshot
            store.markLoaded(0, [metaSnap])

            expect(store.getEntry(0)?.metaTimestamps).toEqual([ts])
        })

        it('bumps version', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(1))
            const v0 = store.version
            store.markLoaded(0, [makeSnapshot(1000)])
            expect(store.version).toBeGreaterThan(v0)
        })
    })

    describe('getAllLoadedSnapshots', () => {
        it('returns empty array when nothing loaded', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            expect(store.getAllLoadedSnapshots()).toEqual([])
        })

        it('merges snapshots from multiple sources in source order', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const ts0a = new Date(Date.UTC(2023, 7, 11, 12, 0, 10)).getTime()
            const ts0b = new Date(Date.UTC(2023, 7, 11, 12, 0, 50)).getTime()
            const ts2 = new Date(Date.UTC(2023, 7, 11, 12, 2, 30)).getTime()

            store.markLoaded(0, [makeSnapshot(ts0b), makeSnapshot(ts0a)])
            store.markLoaded(2, [makeSnapshot(ts2)])

            const all = store.getAllLoadedSnapshots()
            expect(all.map((s) => s.timestamp)).toEqual([ts0a, ts0b, ts2])
        })

        it('caches result until version changes', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(1))
            store.markLoaded(0, [makeSnapshot(100)])

            const first = store.getAllLoadedSnapshots()
            const second = store.getAllLoadedSnapshots()
            expect(first).toBe(second) // same reference
        })
    })

    describe('getSnapshotsByWindowId', () => {
        it('groups snapshots by windowId', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(1))
            store.markLoaded(0, [makeSnapshot(100, 1), makeSnapshot(200, 2), makeSnapshot(300, 1)])

            const byWindow = store.getSnapshotsByWindowId()
            expect(byWindow[1]?.length).toBe(2)
            expect(byWindow[2]?.length).toBe(1)
        })
    })

    describe('getSourceIndexForTimestamp', () => {
        it.each([
            { description: 'timestamp in first source', minute: 0, second: 30, expected: 0 },
            { description: 'timestamp in middle source', minute: 5, second: 30, expected: 5 },
            { description: 'timestamp in last source', minute: 9, second: 30, expected: 9 },
            { description: 'timestamp before all sources', minute: -10, second: 0, expected: 0 },
            { description: 'timestamp after all sources', minute: 100, second: 0, expected: 9 },
        ])('returns $expected for $description', ({ minute, second, expected }) => {
            const store = new SnapshotStore()
            store.setSources(makeSources(10))
            const ts = new Date(Date.UTC(2023, 7, 11, 12, minute, second)).getTime()
            expect(store.getSourceIndexForTimestamp(ts)).toBe(expected)
        })
    })

    describe('canPlayAt', () => {
        it('returns false when no FullSnapshot exists', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            store.markLoaded(0, [makeSnapshot(1000)])
            store.markLoaded(1, [makeSnapshot(2000)])

            const ts = new Date(Date.UTC(2023, 7, 11, 12, 1, 30)).getTime()
            expect(store.canPlayAt(ts)).toBe(false)
        })

        it('returns true with FullSnapshot and continuous coverage', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(5))

            const fsTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()
            store.markLoaded(0, [makeFullSnapshot(fsTs)])
            store.markLoaded(1, [makeSnapshot(fsTs + 60000)])
            store.markLoaded(2, [makeSnapshot(fsTs + 120000)])

            const targetTs = new Date(Date.UTC(2023, 7, 11, 12, 2, 30)).getTime()
            expect(store.canPlayAt(targetTs)).toBe(true)
        })

        it('returns false when there is a gap between FullSnapshot and target', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(10))

            const fsTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()
            store.markLoaded(0, [makeFullSnapshot(fsTs)])
            // Source 1-4 NOT loaded (gap)
            store.markLoaded(5, [makeSnapshot(fsTs + 300000)])

            const targetTs = new Date(Date.UTC(2023, 7, 11, 12, 5, 30)).getTime()
            expect(store.canPlayAt(targetTs)).toBe(false)
        })
    })

    describe('findNearestFullSnapshot', () => {
        it('returns null when no FullSnapshots exist', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            store.markLoaded(0, [makeSnapshot(1000)])

            expect(store.findNearestFullSnapshot(2000)).toBeNull()
        })

        it('finds the nearest FullSnapshot before the target', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(5))

            const fs1 = new Date(Date.UTC(2023, 7, 11, 12, 1, 30)).getTime()
            const fs3 = new Date(Date.UTC(2023, 7, 11, 12, 3, 30)).getTime()

            store.markLoaded(1, [makeFullSnapshot(fs1)])
            store.markLoaded(3, [makeFullSnapshot(fs3)])

            const target = new Date(Date.UTC(2023, 7, 11, 12, 4, 0)).getTime()
            const result = store.findNearestFullSnapshot(target)
            expect(result).toEqual({ sourceIndex: 3, timestamp: fs3 })
        })
    })

    describe('getUnloadedIndicesInRange', () => {
        it.each([
            {
                description: 'returns all indices when nothing is loaded',
                loadedIndices: [] as number[],
                start: 0,
                end: 4,
                expected: [0, 1, 2, 3, 4],
            },
            {
                description: 'returns empty when all loaded',
                loadedIndices: [0, 1, 2, 3, 4],
                start: 0,
                end: 4,
                expected: [],
            },
            {
                description: 'returns only unloaded in range',
                loadedIndices: [0, 2, 4],
                start: 1,
                end: 3,
                expected: [1, 3],
            },
            {
                description: 'clamps to valid range',
                loadedIndices: [],
                start: -5,
                end: 100,
                expected: [0, 1, 2, 3, 4],
            },
        ])('$description', ({ loadedIndices, start, end, expected }) => {
            const store = new SnapshotStore()
            store.setSources(makeSources(5))
            for (const i of loadedIndices) {
                store.markLoaded(i, [makeSnapshot(1000 + i)])
            }
            expect(store.getUnloadedIndicesInRange(start, end)).toEqual(expected)
        })
    })

    describe('getSourceStates', () => {
        it('returns state for each source', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            store.markLoaded(1, [makeSnapshot(2000)])

            const states = store.getSourceStates()
            expect(states).toHaveLength(3)
            expect(states[0].state).toBe('unloaded')
            expect(states[1].state).toBe('loaded')
            expect(states[2].state).toBe('unloaded')
        })
    })

    describe('allLoaded', () => {
        it('is false when not all sources are loaded', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            store.markLoaded(0, [makeSnapshot(1000)])
            expect(store.allLoaded).toBe(false)
        })

        it('is true when all sources are loaded', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(2))
            store.markLoaded(0, [makeSnapshot(1000)])
            store.markLoaded(1, [makeSnapshot(2000)])
            expect(store.allLoaded).toBe(true)
        })

        it('is false for empty store', () => {
            const store = new SnapshotStore()
            expect(store.allLoaded).toBe(false)
        })
    })

    describe('version tracking', () => {
        it('increments on each mutation', () => {
            const store = new SnapshotStore()
            const versions: number[] = [store.version]

            store.setSources(makeSources(3))
            versions.push(store.version)

            store.markLoaded(0, [makeSnapshot(1000)])
            versions.push(store.version)

            store.markLoaded(1, [makeSnapshot(2000)])
            versions.push(store.version)

            // Each version should be strictly increasing
            for (let i = 1; i < versions.length; i++) {
                expect(versions[i]).toBeGreaterThan(versions[i - 1])
            }
        })
    })
})
