import { EventType, eventWithTime } from '@posthog/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { ViewportResolution } from '../snapshot-processing/patch-meta-event'
import { processSourceSnapshots } from './processSourceSnapshots'
import { SourceEntry } from './types'

const MAX_LOADED_SOURCES = 50

export class SnapshotStore {
    private entries: SourceEntry[] = []
    private _version = 0
    private mergedSnapshotsCache: RecordingSnapshot[] | null = null
    private snapshotsByWindowIdCache: Record<number, eventWithTime[]> | null = null
    private lastMergedVersion = -1

    get version(): number {
        return this._version
    }

    setSources(sources: SessionRecordingSnapshotSource[]): void {
        this.entries = sources.map((source, index) => ({
            source,
            index,
            state: 'unloaded',
            processedSnapshots: null,
            fullSnapshotTimestamps: [],
            metaTimestamps: [],
            startMs: source.start_timestamp ? new Date(source.start_timestamp).getTime() : 0,
            endMs: source.end_timestamp ? new Date(source.end_timestamp).getTime() : 0,
        }))
        this.bump()
    }

    get sourceCount(): number {
        return this.entries.length
    }

    getEntry(index: number): SourceEntry | undefined {
        return this.entries[index]
    }

    processAndStore(
        sourceIndex: number,
        rawSnapshots: RecordingSnapshot[],
        viewportFn: (timestamp: number) => ViewportResolution | undefined
    ): void {
        const entry = this.entries[sourceIndex]
        if (!entry) {
            return
        }

        const processed = processSourceSnapshots(rawSnapshots, viewportFn)

        const fullSnapshotTimestamps: number[] = []
        const metaTimestamps: number[] = []
        for (const snap of processed) {
            if (snap.type === EventType.FullSnapshot) {
                fullSnapshotTimestamps.push(snap.timestamp)
            }
            if (snap.type === EventType.Meta) {
                metaTimestamps.push(snap.timestamp)
            }
        }

        entry.state = 'loaded'
        entry.processedSnapshots = processed
        entry.fullSnapshotTimestamps = fullSnapshotTimestamps
        entry.metaTimestamps = metaTimestamps
        this.bump()
    }

    markLoaded(sourceIndex: number, processedSnapshots: RecordingSnapshot[]): void {
        const entry = this.entries[sourceIndex]
        if (!entry) {
            return
        }

        const fullSnapshotTimestamps: number[] = []
        const metaTimestamps: number[] = []
        for (const snap of processedSnapshots) {
            if (snap.type === EventType.FullSnapshot) {
                fullSnapshotTimestamps.push(snap.timestamp)
            }
            if (snap.type === EventType.Meta) {
                metaTimestamps.push(snap.timestamp)
            }
        }

        entry.state = 'loaded'
        entry.processedSnapshots = processedSnapshots
        entry.fullSnapshotTimestamps = fullSnapshotTimestamps
        entry.metaTimestamps = metaTimestamps
        this.bump()
    }

    isSourceLoaded(index: number): boolean {
        return this.entries[index]?.state === 'loaded'
    }

    getAllLoadedSnapshots(): RecordingSnapshot[] {
        if (this.lastMergedVersion === this._version && this.mergedSnapshotsCache) {
            return this.mergedSnapshotsCache
        }

        const result: RecordingSnapshot[] = []
        for (const entry of this.entries) {
            if (entry.state === 'loaded' && entry.processedSnapshots) {
                for (const snap of entry.processedSnapshots) {
                    result.push(snap)
                }
            }
        }
        result.sort((a, b) => a.timestamp - b.timestamp)
        this.mergedSnapshotsCache = result
        this.lastMergedVersion = this._version
        return result
    }

    getSnapshotsByWindowId(): Record<number, eventWithTime[]> {
        if (this.lastMergedVersion === this._version && this.snapshotsByWindowIdCache) {
            return this.snapshotsByWindowIdCache
        }

        // Ensure merged cache is fresh
        this.getAllLoadedSnapshots()

        const result: Record<number, eventWithTime[]> = {}
        const snapshots = this.mergedSnapshotsCache || []
        for (const snapshot of snapshots) {
            const windowId = (snapshot as RecordingSnapshot).windowId
            if (!(windowId in result)) {
                result[windowId] = []
            }
            result[windowId].push(snapshot)
        }
        this.snapshotsByWindowIdCache = result
        return result
    }

    getSourceIndexForTimestamp(ts: number): number {
        for (let i = 0; i < this.entries.length; i++) {
            const entry = this.entries[i]
            if (ts >= entry.startMs && ts <= entry.endMs) {
                return i
            }
        }
        if (this.entries.length > 0 && ts < this.entries[0].startMs) {
            return 0
        }
        return Math.max(0, this.entries.length - 1)
    }

    canPlayAt(ts: number): boolean {
        const fullSnapshotInfo = this.findNearestFullSnapshot(ts)
        if (!fullSnapshotInfo) {
            return false
        }

        const targetIndex = this.getSourceIndexForTimestamp(ts)

        // Check every source from the FullSnapshot's source to the target source is loaded
        for (let i = fullSnapshotInfo.sourceIndex; i <= targetIndex; i++) {
            if (this.entries[i]?.state !== 'loaded') {
                return false
            }
        }
        return true
    }

    findNearestFullSnapshot(ts: number): { sourceIndex: number; timestamp: number } | null {
        let bestTs = -1
        let bestSourceIndex = -1

        for (const entry of this.entries) {
            // Look at persisted metadata (works even for evicted sources)
            for (const fullTs of entry.fullSnapshotTimestamps) {
                if (fullTs <= ts && fullTs > bestTs) {
                    bestTs = fullTs
                    bestSourceIndex = entry.index
                }
            }
        }

        if (bestSourceIndex === -1) {
            return null
        }
        return { sourceIndex: bestSourceIndex, timestamp: bestTs }
    }

    evict(currentSourceIndex: number, maxLoaded: number = MAX_LOADED_SOURCES): void {
        const loadedEntries = this.entries.filter((e) => e.state === 'loaded')
        if (loadedEntries.length <= maxLoaded) {
            return
        }

        // Find the source containing the nearest FullSnapshot before current position
        const currentEntry = this.entries[currentSourceIndex]
        const currentTs = currentEntry ? currentEntry.startMs : 0
        const nearestFull = this.findNearestFullSnapshot(currentTs)
        const protectedIndices = new Set<number>()
        protectedIndices.add(currentSourceIndex)
        if (nearestFull) {
            protectedIndices.add(nearestFull.sourceIndex)
        }

        // Sort loaded entries by distance from current position (furthest first)
        const evictable = loadedEntries
            .filter((e) => !protectedIndices.has(e.index))
            .sort((a, b) => {
                const distA = Math.abs(a.index - currentSourceIndex)
                const distB = Math.abs(b.index - currentSourceIndex)
                return distB - distA
            })

        const toEvict = loadedEntries.length - maxLoaded
        for (let i = 0; i < toEvict && i < evictable.length; i++) {
            evictable[i].state = 'evicted'
            evictable[i].processedSnapshots = null
        }

        if (toEvict > 0) {
            this.bump()
        }
    }

    getUnloadedIndicesInRange(start: number, end: number): number[] {
        const result: number[] = []
        const clampedStart = Math.max(0, start)
        const clampedEnd = Math.min(this.entries.length - 1, end)
        for (let i = clampedStart; i <= clampedEnd; i++) {
            if (this.entries[i]?.state !== 'loaded') {
                result.push(i)
            }
        }
        return result
    }

    private bump(): void {
        this._version++
        this.mergedSnapshotsCache = null
        this.snapshotsByWindowIdCache = null
    }
}
