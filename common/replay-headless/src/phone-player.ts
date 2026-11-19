import { Replayer } from 'posthog-js/rrweb'
import { EventType, type eventWithTime } from 'posthog-js/rrweb-types'

import {
    AudioMuteReplayerPlugin,
    BLOCKED_ELEMENT_STYLE_RULE,
    CanvasReplayerPlugin,
    COMMON_REPLAYER_CONFIG,
    createSegments,
    createWindowIdRegistry,
    keyForSource,
    mapSnapshotsToWindowId,
    mergeInactiveSegments,
    noOpTelemetry,
    parseJsonSnapshots,
    processAllSnapshots,
    type ProcessingCache,
    type RecordingSegment,
    type RecordingSnapshot,
    type SessionRecordingSnapshotSource,
    type SessionRecordingSnapshotSourceResponse,
    SnapshotSourceType,
    type SourceKey,
    speedDependentStyleRules,
} from '@posthog/replay-shared'

import type { PhoneHostCommand, PhonePlayerMessage, PhoneSource } from './phone-protocol'
import { ViewportScaler } from './viewport-scaler'

/** posthog-js takes a full snapshot every 5 minutes, so a moment rarely needs more history than this. */
const LOOKBACK_MS = 5 * 60 * 1000 + 15_000
const AHEAD_MS = 30_000
const BUFFER_AHEAD_MS = 20_000
const BUFFER_BLOCKS = 12
const HISTORY_BLOCKS = 24
const BACKFILL_BLOCKS = 30
/** The snapshots endpoint accepts `end_blob_key - start_blob_key <= 100` for a session or OAuth caller. */
const MAX_RANGE_BLOCKS = 101
const TIME_REPORT_MS = 250
const MIN_SKIP_MS = 1000

interface Target {
    ts: number
    endTs: number | null
    windowId?: number
}

interface ActiveReplayer {
    replayer: Replayer
    root: HTMLElement
    windowId: number
    firstTs: number
    fullSnapshotTs: number
    fromIndex: number
    throughIndex: number
    lastTs: number
    rebuiltForMissingHead: boolean
}

declare global {
    interface Window {
        ReactNativeWebView?: { postMessage: (message: string) => void }
        __phonePlayer?: { command: (command: PhoneHostCommand) => void }
    }
}

function post(message: PhonePlayerMessage): void {
    window.ReactNativeWebView?.postMessage(JSON.stringify(message))
}

function mark(name: string, detail?: Record<string, number | string>): void {
    post({ type: 'mark', name, at: Date.now(), detail })
}

class PhonePlayer {
    private sessionId = ''
    private sources: PhoneSource[] = []
    private loaded = new Map<number, RecordingSnapshot[]>()
    private pending = new Map<number, { from: number; to: number; parts: string[] }>()
    private requested = new Set<number>()
    private nextRequestId = 1
    private registerWindowId = createWindowIdRegistry()
    private cache: ProcessingCache = { snapshots: {} }
    private target: Target | null = null
    private wantPlaying = false
    private speed = 1
    private skipInactivity = true
    private active: ActiveReplayer | null = null
    private segments: RecordingSegment[] = []
    private inactivitySegments: RecordingSegment[] = []
    private segmentSnapshots: RecordingSnapshot[] = []
    private windowEnds = new Map<number, number>()
    private checkpoint: { index: number; timestamp: number } | null = null
    private appending = false
    private buffering = false
    private lastTimeReport = 0
    private endReported = false
    private firstFrameReported = false
    private playingReported = false
    private awaitingTarget = false
    private building = false
    private failed = false
    private scaler: ViewportScaler

    constructor(private container: HTMLElement) {
        this.scaler = new ViewportScaler(container, 0)
        window.addEventListener('resize', () => {
            if (this.active) {
                this.scaler.fitReplayer(this.active.replayer)
            }
        })
        requestAnimationFrame(() => this.tick())
    }

    command(command: PhoneHostCommand): void {
        try {
            this.handle(command)
        } catch (error) {
            this.fail(error)
        }
    }

    private handle(command: PhoneHostCommand): void {
        switch (command.type) {
            case 'init':
                this.sessionId = command.sessionId
                this.sources = command.sources
                this.speed = command.speed
                this.skipInactivity = command.skipInactivity
                return
            case 'prepare':
                this.target = { ts: command.targetTs, endTs: command.endTs }
                this.wantPlaying = command.play
                this.failed = false
                this.playingReported = false
                this.endReported = false
                this.firstFrameReported = false
                mark('prepare', { targetTs: command.targetTs })
                this.moveTo(command.targetTs)
                return
            case 'window': {
                // A tab switch keeps the time: no rebuild and no seek. Blocks past the old end load as playback nears
                // them, through the same buffering as any other playback.
                const ts = this.currentTs() ?? this.target?.ts
                if (ts === undefined) {
                    return
                }
                this.target = { ...this.target, ts: this.target?.ts ?? ts, endTs: command.endTs }
                if (command.endTs === null || command.endTs > ts) {
                    this.endReported = false
                }
                mark('window', { endTs: command.endTs ?? -1 })
                return
            }
            case 'seek':
                this.target = { ts: command.ts, endTs: this.target?.endTs ?? null }
                this.endReported = false
                this.moveTo(command.ts)
                return
            case 'play':
                this.wantPlaying = true
                this.endReported = false
                if (this.active && !this.building) {
                    this.active.replayer.play(this.active.replayer.getCurrentTime())
                    mark('play')
                }
                return
            case 'pause':
                this.wantPlaying = false
                this.playingReported = false
                this.active?.replayer.pause()
                return
            case 'speed':
                this.speed = command.speed
                this.active?.replayer.setConfig({ speed: command.speed })
                return
            case 'skipInactivity':
                this.skipInactivity = command.on
                return
            case 'blocks':
                this.receive(command.requestId, command.text, command.done)
                return
            case 'blocksFailed': {
                const failed = this.pending.get(command.requestId)
                for (let i = failed?.from ?? 0; failed && i <= failed.to; i++) {
                    this.requested.delete(i)
                }
                this.pending.delete(command.requestId)
                this.fail(new Error(command.message))
                return
            }
        }
    }

    private fail(error: unknown): void {
        this.failed = true
        const message = error instanceof Error ? error.message : String(error)
        post({ type: 'status', status: 'error', message })
    }

    private indexAt(ts: number): number {
        let index = 0
        for (let i = 0; i < this.sources.length; i++) {
            if ((this.sources[i] as PhoneSource).startTs <= ts) {
                index = i
            } else {
                break
            }
        }
        return index
    }

    private covers(ts: number): boolean {
        const active = this.active
        return active !== null && ts >= active.fullSnapshotTs && ts <= active.lastTs
    }

    private moveTo(ts: number): void {
        const windowId = this.windowAt(ts)
        if (
            this.covers(ts) &&
            this.active &&
            !this.building &&
            (windowId === null || this.active.windowId === windowId)
        ) {
            const offset = ts - this.active.firstTs
            if (this.wantPlaying) {
                this.active.replayer.play(offset)
            } else {
                this.active.replayer.pause(offset)
            }
            this.awaitingTarget = false
            this.buffering = false
            this.reportTime(true)
            post({ type: 'status', status: 'readyToPlay' })
            this.reportFirstFrame()
            return
        }
        this.awaitingTarget = true
        post({ type: 'status', status: 'loading' })
        this.ensure()
    }

    /** Ask the host for the blocks in [from, to] that are not loaded or on their way, in ranges the API accepts. */
    private request(from: number, to: number): boolean {
        let asked = false
        let start: number | null = null
        const flush = (end: number): void => {
            if (start === null) {
                return
            }
            for (let a = start; a <= end; a += MAX_RANGE_BLOCKS) {
                const b = Math.min(end, a + MAX_RANGE_BLOCKS - 1)
                const requestId = this.nextRequestId++
                this.pending.set(requestId, { from: a, to: b, parts: [] })
                for (let i = a; i <= b; i++) {
                    this.requested.add(i)
                }
                post({ type: 'need', requestId, from: a, to: b })
                mark('need', { requestId, from: a, to: b })
                asked = true
            }
            start = null
        }
        for (let i = Math.max(0, from); i <= Math.min(to, this.sources.length - 1); i++) {
            if (this.loaded.has(i) || this.requested.has(i)) {
                flush(i - 1)
            } else if (start === null) {
                start = i
            }
        }
        flush(Math.min(to, this.sources.length - 1))
        return asked
    }

    private receive(requestId: number, text: string, done: boolean): void {
        const request = this.pending.get(requestId)
        if (!request) {
            return
        }
        request.parts.push(text)
        if (!done) {
            return
        }
        this.pending.delete(requestId)
        const body = request.parts.join('')
        mark('received', { requestId, chars: body.length })
        const lines = body.split('\n').filter(Boolean)
        const snapshots = parseJsonSnapshots(lines, this.sessionId, noOpTelemetry, this.registerWindowId)
        const byBlock = new Map<number, RecordingSnapshot[]>()
        for (let i = request.from; i <= request.to; i++) {
            byBlock.set(i, [])
        }
        for (const snapshot of snapshots) {
            let index = request.to
            for (let i = request.from; i <= request.to; i++) {
                if (snapshot.timestamp <= (this.sources[i] as PhoneSource).endTs) {
                    index = i
                    break
                }
            }
            byBlock.get(index)?.push(snapshot)
        }
        for (const [index, events] of byBlock) {
            this.loaded.set(index, events)
            this.requested.delete(index)
        }
        mark('parsed', { requestId, events: snapshots.length, lines: lines.length })
        void this.afterLoad()
    }

    private async afterLoad(): Promise<void> {
        if (this.building || this.appending || this.failed) {
            return
        }
        if (!this.active || this.awaitingTarget) {
            this.ensure()
            return
        }
        await this.append()
    }

    private contiguousThrough(index: number): number {
        let through = index
        while (this.loaded.has(through + 1)) {
            through += 1
        }
        return through
    }

    private ownerWindow(ts: number, low: number, high: number): number | null {
        let owner: number | null = null
        let firstAfter: number | null = null
        for (let i = low; i <= high; i++) {
            for (const event of this.loaded.get(i) ?? []) {
                if (event.timestamp <= ts) {
                    owner = event.windowId
                } else if (firstAfter === null) {
                    firstAfter = event.windowId
                }
            }
        }
        return owner ?? firstAfter
    }

    private ensure(): void {
        const target = this.target
        if (!target || this.sources.length === 0 || this.building || this.appending || this.failed) {
            return
        }
        const targetIndex = this.indexAt(target.ts)
        const endIndex = Math.max(targetIndex, this.indexAt(Math.min(target.endTs ?? Infinity, target.ts + AHEAD_MS)))
        if (!this.loaded.has(targetIndex)) {
            const lookIndex = this.sources.findIndex((source) => source.endTs >= target.ts - LOOKBACK_MS)
            this.request(Math.max(0, Math.min(lookIndex, targetIndex)), endIndex)
            return
        }
        if (this.request(targetIndex, endIndex)) {
            return
        }
        let low = targetIndex
        while (low > 0 && this.loaded.has(low - 1)) {
            low -= 1
        }
        const windowId = target.windowId ?? this.windowAt(target.ts) ?? this.ownerWindow(target.ts, low, endIndex)
        if (windowId === null) {
            this.fail(new Error('no_snapshots'))
            return
        }
        for (let i = targetIndex; i >= low; i--) {
            const hasFull = (this.loaded.get(i) ?? []).some(
                (event) =>
                    event.type === EventType.FullSnapshot && event.windowId === windowId && event.timestamp <= target.ts
            )
            if (hasFull) {
                void this.build(i, windowId)
                return
            }
        }
        if (low > 0) {
            mark('backfill', { below: low })
            this.request(Math.max(0, low - BACKFILL_BLOCKS), low - 1)
            return
        }
        const later = this.firstFullSnapshotAfter(target.ts, windowId, endIndex)
        if (later === null) {
            this.fail(new Error('no_full_snapshot'))
            return
        }
        this.target = { ...target, ts: later.ts }
        void this.build(later.index, windowId)
    }

    private firstFullSnapshotAfter(
        ts: number,
        windowId: number,
        through: number
    ): { ts: number; index: number } | null {
        for (let i = this.indexAt(ts); i <= through; i++) {
            const event = (this.loaded.get(i) ?? []).find(
                (item) => item.type === EventType.FullSnapshot && item.windowId === windowId && item.timestamp >= ts
            )
            if (event) {
                return { ts: event.timestamp, index: i }
            }
        }
        return null
    }

    private async processed(from: number, through: number): Promise<RecordingSnapshot[]> {
        const sources: SessionRecordingSnapshotSource[] = []
        const bySource: Record<SourceKey, SessionRecordingSnapshotSourceResponse> = {}
        for (let i = from; i <= through; i++) {
            const source: SessionRecordingSnapshotSource = { source: SnapshotSourceType.blob_v2, blob_key: String(i) }
            sources.push(source)
            const key = keyForSource(source)
            if (!(key in this.cache.snapshots)) {
                bySource[key] = { snapshots: [...(this.loaded.get(i) ?? [])], sourceLoaded: true }
            }
        }
        return processAllSnapshots(sources, bySource, this.cache, () => undefined, this.sessionId, noOpTelemetry)
    }

    private async build(fromIndex: number, windowId: number): Promise<void> {
        const target = this.target
        if (!target) {
            return
        }
        this.building = true
        let replaced = false
        try {
            const throughIndex = this.contiguousThrough(fromIndex)
            const snapshots = await this.processed(fromIndex, throughIndex)
            if (this.target?.ts !== target.ts || this.target.windowId !== target.windowId) {
                return
            }
            mark('processed', { fromIndex, throughIndex, events: snapshots.length })
            const windowEvents = mapSnapshotsToWindowId(snapshots)[windowId] ?? []
            let fullIndex = -1
            for (let i = 0; i < windowEvents.length; i++) {
                const event = windowEvents[i] as eventWithTime
                if (event.type === EventType.FullSnapshot && event.timestamp <= target.ts) {
                    fullIndex = i
                }
            }
            if (fullIndex < 0) {
                fullIndex = windowEvents.findIndex((event) => event.type === EventType.FullSnapshot)
            }
            if (fullIndex < 0) {
                throw new Error('no_full_snapshot')
            }
            let startIndex = fullIndex
            const before = windowEvents[fullIndex - 1]
            if (before && before.type === EventType.Meta) {
                startIndex = fullIndex - 1
            }
            const events = windowEvents.slice(startIndex)
            if (events.length < 2) {
                throw new Error('no_snapshots')
            }
            this.replaceReplayer(
                events,
                windowId,
                fromIndex,
                throughIndex,
                (windowEvents[fullIndex] as eventWithTime).timestamp
            )
            this.segmentSnapshots = snapshots
            this.updateSegments()
            this.trimHistory(fromIndex, throughIndex)
            this.checkpoint = null
            this.findCheckpoint()
            replaced = true
        } catch (error) {
            this.fail(error)
        } finally {
            this.building = false
            if (replaced || this.awaitingTarget) {
                void this.afterLoad()
            }
        }
    }

    private replaceReplayer(
        events: eventWithTime[],
        windowId: number,
        fromIndex: number,
        throughIndex: number,
        fullSnapshotTs: number
    ): void {
        const target = this.target as Target
        if (this.active) {
            this.active.replayer.destroy()
            this.active.root.remove()
        }
        const root = document.createElement('div')
        this.container.appendChild(root)
        const replayer = new Replayer(events, {
            root,
            ...COMMON_REPLAYER_CONFIG,
            insertStyleRules: [
                ...(COMMON_REPLAYER_CONFIG.insertStyleRules ?? []),
                BLOCKED_ELEMENT_STYLE_RULE,
                ...speedDependentStyleRules(this.speed),
            ],
            mouseTail: false,
            useVirtualDom: false,
            speed: this.speed,
            plugins: [AudioMuteReplayerPlugin(true), CanvasReplayerPlugin(events)],
        })
        const firstTs = (events[0] as eventWithTime).timestamp
        const active: ActiveReplayer = {
            replayer,
            root,
            windowId,
            firstTs,
            fullSnapshotTs,
            fromIndex,
            throughIndex,
            lastTs: (events[events.length - 1] as eventWithTime).timestamp,
            rebuiltForMissingHead: false,
        }
        this.active = active
        this.awaitingTarget = false
        this.buffering = false
        let rebuilt = false
        replayer.on('fullsnapshot-rebuilded', () => {
            if (!rebuilt) {
                rebuilt = true
                mark('fullSnapshotBuilt')
            }
        })
        replayer.on('finish', () => this.onFinish(active))
        this.scaler.attachToReplayer(replayer)
        const offset = Math.max(0, target.ts - firstTs)
        replayer.pause(offset)
        mark('fastForwardDone', { offsetMs: offset, events: events.length })
        if (!replayer.iframe.contentDocument?.head && !active.rebuiltForMissingHead) {
            mark('missingHeadRebuild')
            active.rebuiltForMissingHead = true
            replayer.pause(offset)
        }
        if (this.wantPlaying) {
            replayer.play(offset)
        }
        post({ type: 'status', status: 'readyToPlay' })
        this.reportTime(true)
        this.reportFirstFrame()
    }

    private reportFirstFrame(): void {
        if (this.firstFrameReported) {
            return
        }
        this.firstFrameReported = true
        requestAnimationFrame(() =>
            requestAnimationFrame(() => {
                const ts = this.currentTs()
                mark('firstFrame')
                post({ type: 'firstFrame', ts: ts ?? 0 })
            })
        )
    }

    private updateSegments(): void {
        const snapshots = this.segmentSnapshots
        const windows = mapSnapshotsToWindowId(snapshots)
        this.windowEnds = new Map(
            Object.entries(windows).map(([id, events]) => [
                Number(id),
                events[events.length - 1]?.timestamp ?? -Infinity,
            ])
        )
        this.segments = createSegments(
            snapshots,
            snapshots[0]?.timestamp ?? null,
            snapshots[snapshots.length - 1]?.timestamp ?? null,
            null,
            windows
        )
        this.inactivitySegments = mergeInactiveSegments(this.segments)
    }

    private windowAt(ts: number): number | null {
        let gapOwner: number | null = null
        for (const segment of this.segments) {
            if (segment.startTimestamp > ts) {
                break
            }
            const { windowId } = segment
            if (windowId == null || segment.endTimestamp < ts) {
                continue
            }
            if (segment.isActive) {
                return windowId
            }
            if (!this.skipInactivity && segment.kind === 'gap' && ts <= (this.windowEnds.get(windowId) ?? -Infinity)) {
                gapOwner ??= windowId
            }
        }
        return gapOwner
    }

    private mergeSegmentSnapshots(snapshots: readonly RecordingSnapshot[]): void {
        const first = snapshots[0]
        if (!first) {
            return
        }
        // Blocks can overlap. Merge only the tail that can contain events from the new batch.
        const timeline = this.segmentSnapshots
        let start = timeline.length
        while (start > 0 && timeline[start - 1].timestamp > first.timestamp) {
            start--
        }
        const overlap = timeline.splice(start)
        let index = 0
        for (const snapshot of snapshots) {
            while (index < overlap.length && overlap[index].timestamp <= snapshot.timestamp) {
                timeline.push(overlap[index++])
            }
            timeline.push(snapshot)
        }
        while (index < overlap.length) {
            timeline.push(overlap[index++])
        }
    }

    private trimHistory(from: number, through: number): void {
        for (const index of this.loaded.keys()) {
            if (index < from || index > through + BUFFER_BLOCKS) {
                this.loaded.delete(index)
                const source: SessionRecordingSnapshotSource = {
                    source: SnapshotSourceType.blob_v2,
                    blob_key: String(index),
                }
                delete this.cache.snapshots[keyForSource(source)]
            }
        }
    }

    private findCheckpoint(fromIndex = 0): void {
        const active = this.active
        if (!active || this.checkpoint) {
            return
        }
        for (
            let index = Math.max(fromIndex, active.fromIndex + HISTORY_BLOCKS);
            index <= active.throughIndex;
            index++
        ) {
            const full = this.loaded
                .get(index)
                ?.find((event) => event.windowId === active.windowId && event.type === EventType.FullSnapshot)
            if (full) {
                this.checkpoint = { index, timestamp: full.timestamp }
                return
            }
        }
    }

    private async append(): Promise<void> {
        const active = this.active
        if (!active) {
            return
        }
        const through = this.contiguousThrough(active.throughIndex)
        if (through === active.throughIndex) {
            this.trimHistory(active.fromIndex, active.throughIndex)
            return
        }

        this.appending = true
        try {
            const firstNewBlock = active.throughIndex + 1
            const snapshots = await this.processed(firstNewBlock, through)
            this.mergeSegmentSnapshots(snapshots)
            for (const snapshot of snapshots) {
                if (snapshot.windowId === active.windowId && snapshot.timestamp >= active.lastTs) {
                    active.replayer.addEvent(snapshot)
                }
            }
            active.throughIndex = through
            const previousEnd = active.lastTs
            this.updateSegments()
            active.lastTs = Math.max(previousEnd, this.windowEnds.get(active.windowId) ?? previousEnd)
            this.findCheckpoint(firstNewBlock)
            if (this.awaitingTarget) {
                return
            }
            mark('appended', { events: snapshots.length, throughIndex: through })
            if (this.buffering && active.lastTs > previousEnd) {
                this.buffering = false
                post({ type: 'status', status: 'readyToPlay' })
                if (this.wantPlaying && !this.endReported) {
                    active.replayer.play(Math.max(0, previousEnd - active.firstTs))
                }
            } else if (this.buffering) {
                this.continueAfterWindow(active)
            }
        } catch (error) {
            this.fail(error)
        } finally {
            this.appending = false
            if (this.awaitingTarget || this.contiguousThrough(through) > through) {
                void this.afterLoad()
            }
        }
    }

    private switchWindow(windowId: number, timestamp: number): void {
        this.active?.replayer.pause()
        this.target = { ts: timestamp, endTs: this.target?.endTs ?? null, windowId }
        this.awaitingTarget = true
        this.ensure()
    }

    private onFinish(active: ActiveReplayer): void {
        if (active === this.active && this.wantPlaying && !this.building && !this.endReported) {
            this.continueAfterWindow(active)
        }
    }

    private continueAfterWindow(active: ActiveReplayer): void {
        const end = this.target?.endTs
        for (const segment of this.segments) {
            const windowId = segment.windowId
            const resumeAt = Math.max(active.lastTs, segment.startTimestamp)
            if (
                segment.kind === 'window' &&
                windowId != null &&
                windowId !== active.windowId &&
                segment.endTimestamp > active.lastTs &&
                (this.windowEnds.get(windowId) ?? -Infinity) > resumeAt &&
                (end == null || resumeAt < end)
            ) {
                this.switchWindow(windowId, resumeAt)
                return
            }
        }

        const last = end == null ? this.sources.length - 1 : this.indexAt(end)
        if (active.throughIndex < last) {
            if (!this.buffering) {
                this.buffering = true
                post({ type: 'status', status: 'loading' })
            }
            this.request(active.throughIndex + 1, Math.min(last, active.throughIndex + BUFFER_BLOCKS))
            return
        }
        this.reportEnd()
    }

    private reportEnd(): void {
        if (this.endReported) {
            return
        }
        this.endReported = true
        if (this.buffering) {
            this.buffering = false
            post({ type: 'status', status: 'readyToPlay' })
        }
        this.wantPlaying = false
        this.active?.replayer.pause()
        this.reportTime(true)
        post({ type: 'ended' })
    }

    private currentTs(): number | null {
        const active = this.active
        return active ? active.firstTs + Math.max(0, active.replayer.getCurrentTime()) : null
    }

    private reportTime(force: boolean): void {
        const ts = this.currentTs()
        const now = Date.now()
        if (ts === null || (!force && now - this.lastTimeReport < TIME_REPORT_MS)) {
            return
        }
        this.lastTimeReport = now
        const playing = this.wantPlaying && !this.building
        if (playing && !this.playingReported) {
            this.playingReported = true
            mark('playing')
        }
        post({ type: 'time', ts, playing })
    }

    private tick(): void {
        requestAnimationFrame(() => this.tick())
        const active = this.active
        const ts = this.currentTs()
        if (!active || ts === null || this.building || this.awaitingTarget || !this.wantPlaying || this.endReported) {
            return
        }
        const target = this.target
        if (target?.endTs != null && ts >= target.endTs) {
            this.reportEnd()
            return
        }
        if (this.buffering) {
            return
        }
        if (!this.appending) {
            const windowId = this.windowAt(ts)
            if (windowId !== null && windowId !== active.windowId) {
                this.switchWindow(windowId, ts)
                return
            }
            // rrweb retains its events. Rebase on a newer full snapshot before dropping the older blocks.
            if (this.checkpoint && this.checkpoint.timestamp <= ts) {
                this.target = { ts, endTs: target?.endTs ?? null, windowId: active.windowId }
                active.replayer.pause()
                void this.build(this.checkpoint.index, active.windowId)
                return
            }
        }
        if (this.skipInactivity) {
            const gap = this.inactivitySegments.find(
                (segment) =>
                    !segment.isActive &&
                    segment.kind !== 'buffer' &&
                    ts >= segment.startTimestamp &&
                    ts < segment.endTimestamp
            )
            if (gap && gap.endTimestamp - ts > MIN_SKIP_MS) {
                const to = Math.min(gap.endTimestamp, active.lastTs)
                active.replayer.play(to - active.firstTs)
                mark('skippedInactivity', { fromTs: ts, toTs: to })
            }
        }
        const through = this.sources[active.throughIndex]
        const windowLoaded = target?.endTs != null && through !== undefined && through.endTs >= target.endTs
        if (
            through &&
            !windowLoaded &&
            active.throughIndex < this.sources.length - 1 &&
            ts > through.endTs - BUFFER_AHEAD_MS
        ) {
            const last = target?.endTs != null ? this.indexAt(target.endTs) : active.throughIndex + BUFFER_BLOCKS
            this.request(active.throughIndex + 1, Math.min(last, active.throughIndex + BUFFER_BLOCKS))
        }
        this.reportTime(false)
    }
}

const container = document.getElementById('content')
if (container) {
    const player = new PhonePlayer(container)
    window.__phonePlayer = { command: (command) => player.command(command) }
    window.addEventListener('error', (event) => post({ type: 'log', level: 'error', message: String(event.message) }))
    mark('documentStart', { at: Math.round(performance.timeOrigin) })
    post({ type: 'loaded' })
}
