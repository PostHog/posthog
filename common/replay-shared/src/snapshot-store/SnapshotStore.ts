import { EventType, eventWithTime } from 'posthog-js/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '../types'
import { FullSnapshotRef, SourceEntry, SourceLoadingState } from './types'

export class SnapshotStore {
    private entries: SourceEntry[] = []
    private _version = 0
    private mergedSnapshotsCache: RecordingSnapshot[] | null = null
    private snapshotsByWindowIdCache: Record<number, eventWithTime[]> | null = null

    get version(): number {
        return this._version
    }

    setSources(sources: SessionRecordingSnapshotSource[]): void {
        const existingByKey = new Map<string, SourceEntry>()
        for (const entry of this.entries) {
            if (entry.source.blob_key) {
                existingByKey.set(entry.source.blob_key, entry)
            }
        }

        this.entries = sources.map((source, index) => {
            const existing = source.blob_key ? existingByKey.get(source.blob_key) : undefined
            if (existing) {
                existing.index = index
                return existing
            }
            return {
                source,
                index,
                state: 'unloaded' as const,
                processedSnapshots: null,
                fullSnapshots: [],
                metaTimestamps: [],
                startMs: source.start_timestamp ? new Date(source.start_timestamp).getTime() : 0,
                endMs: source.end_timestamp ? new Date(source.end_timestamp).getTime() : 0,
            }
        })
        this.bump()
    }

    get sourceCount(): number {
        return this.entries.length
    }

    get allLoaded(): boolean {
        return this.entries.length > 0 && this.entries.every((e) => e.state === 'loaded')
    }

    getEntry(index: number): SourceEntry | undefined {
        return this.entries[index]
    }

    markLoaded(sourceIndex: number, processedSnapshots: RecordingSnapshot[]): void {
        const entry = this.entries[sourceIndex]
        if (!entry) {
            return
        }

        processedSnapshots.sort((a, b) => a.timestamp - b.timestamp)

        const fullSnapshots: FullSnapshotRef[] = []
        const metaTimestamps: number[] = []
        for (const snap of processedSnapshots) {
            if (snap.type === EventType.FullSnapshot) {
                fullSnapshots.push({ timestamp: snap.timestamp, windowId: snap.windowId })
            }
            if (snap.type === EventType.Meta) {
                metaTimestamps.push(snap.timestamp)
            }
        }

        entry.state = 'loaded'
        entry.processedSnapshots = processedSnapshots
        entry.fullSnapshots = fullSnapshots
        entry.metaTimestamps = metaTimestamps
        this.bump()
    }

    getAllLoadedSnapshots(): RecordingSnapshot[] {
        if (this.mergedSnapshotsCache) {
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
        this.mergedSnapshotsCache = result
        return result
    }

    getSnapshotsByWindowId(): Record<number, eventWithTime[]> {
        if (this.snapshotsByWindowIdCache) {
            return this.snapshotsByWindowIdCache
        }

        const snapshots = this.getAllLoadedSnapshots()

        const result: Record<number, eventWithTime[]> = {}
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

    /**
     * Returns the index of the source whose timestamp range contains `ts`,
     * or the nearest source if `ts` falls outside any range. Returns `null`
     * when the store has no sources yet — callers MUST handle this case
     * explicitly rather than conflating it with "source 0", which is a
     * valid result and hides initial-load races (see #53893).
     */
    getSourceIndexForTimestamp(ts: number): number | null {
        if (this.entries.length === 0) {
            return null
        }
        for (let i = 0; i < this.entries.length; i++) {
            const entry = this.entries[i]
            if (ts >= entry.startMs && ts <= entry.endMs) {
                return i
            }
            if (ts < entry.startMs) {
                return Math.max(0, i - 1)
            }
        }
        return Math.max(0, this.entries.length - 1)
    }

    canPlayAt(ts: number, windowId?: number): boolean {
        if (this.entries.length === 0) {
            return false
        }
        // Timestamp is beyond all known source data — can't play yet
        if (ts > this.entries[this.entries.length - 1].endMs) {
            return false
        }

        const fullSnapshotInfo = this.findNearestFullSnapshot(ts, windowId)
        if (!fullSnapshotInfo) {
            return false
        }

        const targetIndex = this.getSourceIndexForTimestamp(ts)
        if (targetIndex === null) {
            return false
        }

        for (let i = fullSnapshotInfo.sourceIndex; i <= targetIndex; i++) {
            if (this.entries[i]?.state !== 'loaded') {
                return false
            }
        }
        return true
    }

    /**
     * Returns the latest loaded FullSnapshot at or before `ts`, or null if none.
     * When `windowId` is given, only FullSnapshots captured in that window count —
     * rrweb renders one window at a time, so another window's FullSnapshot cannot
     * make this window's events renderable.
     */
    findNearestFullSnapshot(ts: number, windowId?: number): { sourceIndex: number; timestamp: number } | null {
        let bestTs = -1
        let bestSourceIndex = -1

        for (const entry of this.entries) {
            for (const fullSnapshot of entry.fullSnapshots) {
                if (windowId !== undefined && fullSnapshot.windowId !== windowId) {
                    continue
                }
                if (fullSnapshot.timestamp <= ts && fullSnapshot.timestamp > bestTs) {
                    bestTs = fullSnapshot.timestamp
                    bestSourceIndex = entry.index
                }
            }
        }

        if (bestSourceIndex === -1) {
            return null
        }
        return { sourceIndex: bestSourceIndex, timestamp: bestTs }
    }

    /**
     * Returns all loaded FullSnapshots at or after `ts`, sorted by timestamp.
     * Used to recover playback when the data before `ts` has no FullSnapshot to
     * render from (e.g. the initial full snapshot was lost at capture time).
     */
    fullSnapshotsAfter(ts: number): (FullSnapshotRef & { sourceIndex: number })[] {
        const result: (FullSnapshotRef & { sourceIndex: number })[] = []
        for (const entry of this.entries) {
            for (const fullSnapshot of entry.fullSnapshots) {
                if (fullSnapshot.timestamp >= ts) {
                    result.push({ ...fullSnapshot, sourceIndex: entry.index })
                }
            }
        }
        return result.sort((a, b) => a.timestamp - b.timestamp)
    }

    syncFullSnapshotTimestamps(processedSnapshots: RecordingSnapshot[]): boolean {
        let changed = false
        for (const entry of this.entries) {
            if (entry.state !== 'loaded') {
                continue
            }
            const fullSnapshots: FullSnapshotRef[] = []
            for (const snap of processedSnapshots) {
                if (
                    snap.type === EventType.FullSnapshot &&
                    snap.timestamp >= entry.startMs &&
                    snap.timestamp <= entry.endMs
                ) {
                    fullSnapshots.push({ timestamp: snap.timestamp, windowId: snap.windowId })
                }
            }
            fullSnapshots.sort((a, b) => a.timestamp - b.timestamp)
            if (
                fullSnapshots.length > 0 &&
                (fullSnapshots.length !== entry.fullSnapshots.length ||
                    fullSnapshots.some(
                        (fs, j) =>
                            fs.timestamp !== entry.fullSnapshots[j].timestamp ||
                            fs.windowId !== entry.fullSnapshots[j].windowId
                    ))
            ) {
                entry.fullSnapshots = fullSnapshots
                changed = true
            }
        }
        if (changed) {
            this.bump()
        }
        return changed
    }

    clearSnapshotData(): void {
        for (const entry of this.entries) {
            entry.processedSnapshots = null
        }
        this.mergedSnapshotsCache = null
        this.snapshotsByWindowIdCache = null
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

    getSourceStates(): SourceLoadingState[] {
        return this.entries.map((e) => ({ startMs: e.startMs, endMs: e.endMs, state: e.state }))
    }

    private bump(): void {
        this._version++
        this.mergedSnapshotsCache = null
        this.snapshotsByWindowIdCache = null
    }
}
