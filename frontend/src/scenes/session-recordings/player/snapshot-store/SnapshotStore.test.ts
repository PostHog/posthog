import { EventType } from 'posthog-js/rrweb-types'

import { SnapshotStore } from '@posthog/replay-shared'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { markLoaded } from './test-utils'

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

        it('preserves loaded entries when sources grow', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            markLoaded(store, 0, [makeFullSnapshot(1000)])
            markLoaded(store, 1, [makeSnapshot(2000)])

            // Live recording adds 2 new sources
            store.setSources(makeSources(5))

            expect(store.sourceCount).toBe(5)
            expect(store.getEntry(0)?.state).toBe('loaded')
            expect(store.getEntry(1)?.state).toBe('loaded')
            expect(store.getEntry(2)?.state).toBe('unloaded')
            expect(store.getEntry(3)?.state).toBe('unloaded')
            expect(store.getEntry(4)?.state).toBe('unloaded')
            expect(store.getEntry(0)?.fullSnapshots).toEqual([{ timestamp: 1000, windowId: 1 }])
        })

        it('preserves loaded snapshots through source growth', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(2))
            markLoaded(store, 0, [makeFullSnapshot(1000)])

            store.setSources(makeSources(3))

            expect(store.getEntry(0)?.processedSnapshots).toHaveLength(1)
            expect(store.getEntry(0)?.processedSnapshots?.[0].timestamp).toBe(1000)
        })
    })

    describe('markFetched + markProcessed seeding', () => {
        it('marks source as loaded and extracts FullSnapshot timestamps', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const ts = new Date(Date.UTC(2023, 7, 11, 12, 1, 30)).getTime()
            const snaps = [makeFullSnapshot(ts), makeSnapshot(ts + 100)]
            markLoaded(store, 1, snaps)

            expect(store.getEntry(1)?.state).toBe('loaded')
            expect(store.getEntry(0)?.state).toBe('unloaded')
            expect(store.getEntry(1)?.fullSnapshots).toEqual([{ timestamp: ts, windowId: 1 }])
        })

        it('bumps version', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(1))
            const v0 = store.version
            markLoaded(store, 0, [makeSnapshot(1000)])
            expect(store.version).toBeGreaterThan(v0)
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

        it('handles timestamp in gap between non-contiguous sources', () => {
            const store = new SnapshotStore()
            // Source 0: minute 0-1, Source 1: minute 5-6 (gap between 1 and 5)
            store.setSources([makeSource(0, 0, 1), makeSource(1, 5, 6)])

            // Timestamp at minute 3 falls in the gap
            const gapTs = new Date(Date.UTC(2023, 7, 11, 12, 3, 0)).getTime()
            const result = store.getSourceIndexForTimestamp(gapTs)
            // Should return source 0 (the one before the gap) since ts < source 1's startMs
            expect(result).toBe(0)
        })

        it('returns null for an empty store (not 0, which would be ambiguous with source 0)', () => {
            // Regression guard for #53893: before this change, an empty store
            // returned 0 for any timestamp, and callers couldn't distinguish
            // "empty — I don't know" from "timestamp falls in source 0".
            const store = new SnapshotStore()
            expect(store.getSourceIndexForTimestamp(Date.now())).toBeNull()
        })
    })

    describe('canPlayAt', () => {
        it('returns false when store has no sources', () => {
            const store = new SnapshotStore()
            expect(store.canPlayAt(1000)).toBe(false)
        })

        it('returns false when no FullSnapshot exists', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            markLoaded(store, 0, [makeSnapshot(1000)])
            markLoaded(store, 1, [makeSnapshot(2000)])

            const ts = new Date(Date.UTC(2023, 7, 11, 12, 1, 30)).getTime()
            expect(store.canPlayAt(ts)).toBe(false)
        })

        it('returns true with FullSnapshot and continuous coverage', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(5))

            const fsTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()
            markLoaded(store, 0, [makeFullSnapshot(fsTs)])
            markLoaded(store, 1, [makeSnapshot(fsTs + 60000)])
            markLoaded(store, 2, [makeSnapshot(fsTs + 120000)])

            const targetTs = new Date(Date.UTC(2023, 7, 11, 12, 2, 30)).getTime()
            expect(store.canPlayAt(targetTs)).toBe(true)
        })

        it('returns false when there is a gap between FullSnapshot and target', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(10))

            const fsTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()
            markLoaded(store, 0, [makeFullSnapshot(fsTs)])
            // Source 1-4 NOT loaded (gap)
            markLoaded(store, 5, [makeSnapshot(fsTs + 300000)])

            const targetTs = new Date(Date.UTC(2023, 7, 11, 12, 5, 30)).getTime()
            expect(store.canPlayAt(targetTs)).toBe(false)
        })

        it('returns true when FullSnapshot is in the same source as the target', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const fsTs = new Date(Date.UTC(2023, 7, 11, 12, 1, 10)).getTime()
            const targetTs = new Date(Date.UTC(2023, 7, 11, 12, 1, 50)).getTime()
            markLoaded(store, 0, [makeSnapshot(1000)])
            markLoaded(store, 1, [makeFullSnapshot(fsTs), makeSnapshot(targetTs)])

            expect(store.canPlayAt(targetTs)).toBe(true)
        })

        it('resolves timestamps beyond all source data to the loaded tail', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(5))

            const fsTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()
            const beyondTs = new Date(Date.UTC(2023, 7, 11, 13, 0, 0)).getTime()

            // Tail not loaded yet: a beyond-end position cannot render
            markLoaded(store, 0, [makeFullSnapshot(fsTs)])
            expect(store.canPlayAt(beyondTs)).toBe(false)

            // Fully loaded: a beyond-end position renders the last frame without loading anything else
            for (let i = 1; i < 5; i++) {
                markLoaded(store, i, [makeSnapshot(fsTs + i * 60000)])
            }
            expect(store.canPlayAt(beyondTs)).toBe(true)
        })
    })

    describe('findNearestFullSnapshot', () => {
        it('returns null when no FullSnapshots exist', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            markLoaded(store, 0, [makeSnapshot(1000)])

            expect(store.findNearestFullSnapshot(2000)).toBeNull()
        })

        it('finds the nearest FullSnapshot before the target', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(5))

            const fs1 = new Date(Date.UTC(2023, 7, 11, 12, 1, 30)).getTime()
            const fs3 = new Date(Date.UTC(2023, 7, 11, 12, 3, 30)).getTime()

            markLoaded(store, 1, [makeFullSnapshot(fs1)])
            markLoaded(store, 3, [makeFullSnapshot(fs3)])

            const target = new Date(Date.UTC(2023, 7, 11, 12, 4, 0)).getTime()
            const result = store.findNearestFullSnapshot(target)
            expect(result).toEqual({ sourceIndex: 3, timestamp: fs3 })
        })

        it('picks the latest when multiple FullSnapshots exist in the same source', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const fs1 = new Date(Date.UTC(2023, 7, 11, 12, 1, 10)).getTime()
            const fs2 = new Date(Date.UTC(2023, 7, 11, 12, 1, 40)).getTime()

            markLoaded(store, 1, [makeFullSnapshot(fs1), makeFullSnapshot(fs2)])

            const target = new Date(Date.UTC(2023, 7, 11, 12, 2, 0)).getTime()
            const result = store.findNearestFullSnapshot(target)
            expect(result).toEqual({ sourceIndex: 1, timestamp: fs2 })
        })

        it('only counts FullSnapshots of the given window when windowId is passed', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const fs1 = new Date(Date.UTC(2023, 7, 11, 12, 1, 10)).getTime()
            const fs2 = new Date(Date.UTC(2023, 7, 11, 12, 1, 40)).getTime()

            markLoaded(store, 1, [makeFullSnapshot(fs1, 1), makeFullSnapshot(fs2, 2)])

            const target = new Date(Date.UTC(2023, 7, 11, 12, 2, 0)).getTime()
            expect(store.findNearestFullSnapshot(target, 1)).toEqual({ sourceIndex: 1, timestamp: fs1 })
            expect(store.findNearestFullSnapshot(target, 2)).toEqual({ sourceIndex: 1, timestamp: fs2 })
            expect(store.findNearestFullSnapshot(target, 3)).toBeNull()
        })
    })

    describe('fullSnapshotsAfter', () => {
        it('returns empty array when no FullSnapshots exist', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            markLoaded(store, 0, [makeSnapshot(1000)])

            expect(store.fullSnapshotsAfter(0)).toEqual([])
        })

        it('returns FullSnapshots at or after the target, sorted by timestamp', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(5))

            const fs1 = new Date(Date.UTC(2023, 7, 11, 12, 1, 30)).getTime()
            const fs3 = new Date(Date.UTC(2023, 7, 11, 12, 3, 30)).getTime()

            markLoaded(store, 3, [makeFullSnapshot(fs3, 2)])
            markLoaded(store, 1, [makeFullSnapshot(fs1, 1)])

            expect(store.fullSnapshotsAfter(fs1)).toEqual([
                { timestamp: fs1, windowId: 1, sourceIndex: 1 },
                { timestamp: fs3, windowId: 2, sourceIndex: 3 },
            ])
        })

        it('excludes FullSnapshots before the target', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(5))

            const fs1 = new Date(Date.UTC(2023, 7, 11, 12, 1, 30)).getTime()
            const fs3 = new Date(Date.UTC(2023, 7, 11, 12, 3, 30)).getTime()

            markLoaded(store, 1, [makeFullSnapshot(fs1)])
            markLoaded(store, 3, [makeFullSnapshot(fs3)])

            expect(store.fullSnapshotsAfter(fs1 + 1)).toEqual([{ timestamp: fs3, windowId: 1, sourceIndex: 3 }])
        })
    })

    describe('fetched lifecycle', () => {
        it('fetched sources are not playable until a processing pass promotes them', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(2))
            const fsTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()

            store.markFetched(0, [makeFullSnapshot(fsTs), makeSnapshot(fsTs + 100)])
            store.markFetched(1, [makeSnapshot(fsTs + 60000)])

            // fetched data is indexed but not renderable, and not refetchable either
            expect(store.canPlayAt(fsTs + 100)).toBe(false)
            expect(store.allLoaded).toBe(false)
            expect(store.getUnloadedIndicesInRange(0, 1)).toEqual([0, 1])
            expect(store.getUnfetchedIndicesInRange(0, 1)).toEqual([])

            expect(store.markProcessed([0, 1])).toBe(true)

            expect(store.canPlayAt(fsTs + 100)).toBe(true)
            expect(store.allLoaded).toBe(true)
            expect(store.getUnloadedIndicesInRange(0, 1)).toEqual([])
        })
    })

    describe('syncFullSnapshotTimestamps', () => {
        it('syncs synthetic full snapshot timestamps from processed results', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const snapTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()
            markLoaded(store, 0, [makeSnapshot(snapTs)])

            expect(store.findNearestFullSnapshot(snapTs)).toBeNull()

            const syntheticFull = makeFullSnapshot(snapTs - 1)
            const changed = store.syncFullSnapshotTimestamps([syntheticFull])

            expect(changed).toBe(true)
            expect(store.findNearestFullSnapshot(snapTs)).toEqual({ sourceIndex: 0, timestamp: snapTs - 1 })
        })

        it('makes canPlayAt return true after syncing mobile full snapshots', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const snapTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()
            markLoaded(store, 0, [makeSnapshot(snapTs)])

            expect(store.canPlayAt(snapTs)).toBe(false)

            store.syncFullSnapshotTimestamps([makeFullSnapshot(snapTs - 1)])

            expect(store.canPlayAt(snapTs)).toBe(true)
        })

        it('indexes synthesized full snapshots that fall between source metadata ranges', () => {
            const store = new SnapshotStore()
            const iso = (second: number): string => new Date(Date.UTC(2023, 7, 11, 12, 0, second)).toISOString()
            const at = (second: number): number => new Date(Date.UTC(2023, 7, 11, 12, 0, second)).getTime()
            store.setSources([
                { source: 'blob_v2', blob_key: 'a', start_timestamp: iso(0), end_timestamp: iso(50) },
                { source: 'blob_v2', blob_key: 'b', start_timestamp: iso(56), end_timestamp: iso(110) },
            ] as any)
            markLoaded(store, 0, [makeSnapshot(at(10))])
            markLoaded(store, 1, [makeSnapshot(at(70))])

            // mobile processing synthesizes a FullSnapshot at screenshot.timestamp - 1, which can land between blob ranges
            const changed = store.syncFullSnapshotTimestamps([makeFullSnapshot(at(55))])

            expect(changed).toBe(true)
            expect(store.findNearestFullSnapshot(at(70))).toMatchObject({ timestamp: at(55) })
        })

        it.each([
            {
                description: 'returns false when timestamps are unchanged',
                loadSource: true,
            },
            {
                description: 'skips unloaded entries',
                loadSource: false,
            },
        ])('$description', ({ loadSource }) => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))

            const fsTs = new Date(Date.UTC(2023, 7, 11, 12, 0, 30)).getTime()
            if (loadSource) {
                markLoaded(store, 0, [makeFullSnapshot(fsTs)])
            }

            const versionBefore = store.version
            const changed = store.syncFullSnapshotTimestamps([makeFullSnapshot(fsTs)])

            expect(changed).toBe(false)
            expect(store.version).toBe(versionBefore)
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
                markLoaded(store, i, [makeSnapshot(1000 + i)])
            }
            expect(store.getUnloadedIndicesInRange(start, end)).toEqual(expected)
        })
    })

    describe('getSourceStates', () => {
        it('returns state for each source', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            markLoaded(store, 1, [makeSnapshot(2000)])

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
            markLoaded(store, 0, [makeSnapshot(1000)])
            expect(store.allLoaded).toBe(false)
        })

        it('is true when all sources are loaded', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(2))
            markLoaded(store, 0, [makeSnapshot(1000)])
            markLoaded(store, 1, [makeSnapshot(2000)])
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

            markLoaded(store, 0, [makeSnapshot(1000)])
            versions.push(store.version)

            markLoaded(store, 1, [makeSnapshot(2000)])
            versions.push(store.version)

            // Each version should be strictly increasing
            for (let i = 1; i < versions.length; i++) {
                expect(versions[i]).toBeGreaterThan(versions[i - 1])
            }
        })
    })
})
