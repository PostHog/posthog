import { Replayer } from 'posthog-js/rrweb'
import { EventType, type eventWithTime } from 'posthog-js/rrweb-types'

import {
    AudioMuteReplayerPlugin,
    CanvasReplayerPlugin,
    CorsPlugin,
    COMMON_REPLAYER_CONFIG,
    HLSPlayerPlugin,
    noOpTelemetry,
    processAllSnapshots,
    speedDependentStyleRules,
    createSegments,
    getHrefFromSnapshot,
    mapSnapshotsToWindowId,
    mergeInactiveSegments,
    type ProcessingCache,
    type RecordingSegment,
    type ViewportResolution,
} from '@posthog/replay-shared'

import { loadAllSources } from './data-loader'
import type { HostBridge } from './host-bridge'
import type { PlaybackWindow } from './playback-controller'
import type { PlayerConfig, ViewportEvent } from './types'

export interface ReplayerWindow extends PlaybackWindow {
    /** The element the window's replayer renders into, shown only while the window is on screen. */
    root: HTMLElement
    /** The first page URL the window recorded, before any event has played. */
    initialURL: string
}

/** Why no window could be replayed: nothing loaded yet, or snapshots that no window can be drawn from. */
export type ReplayerSetupFailure = 'no_snapshots' | 'no_full_snapshot'

/** Each window keeps its own iframe and DOM alive for the whole render, and window ids come from the recording. */
const MAX_REPLAYED_WINDOWS = 20

/** The windows with the most active time, which are the ones worth their memory when a session opened too many. */
function busiestWindowIds(segments: RecordingSegment[], limit: number): Set<number> {
    const activeMs = new Map<number, number>()
    for (const seg of segments) {
        if (seg.windowId != null) {
            activeMs.set(seg.windowId, (activeMs.get(seg.windowId) ?? 0) + (seg.isActive ? seg.durationMs : 0))
        }
    }
    const ranked = [...activeMs.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit)
    return new Set(ranked.map(([windowId]) => windowId))
}

function firstHref(events: eventWithTime[]): string {
    for (const event of events) {
        const href = getHrefFromSnapshot(event)
        if (href) {
            return href
        }
    }
    return ''
}

export interface ReplayerSetup {
    /** Ordered by when each window first appears in the recording. */
    windows: ReplayerWindow[]
    segments: RecordingSegment[]
    firstTimestamp: number
}

function buildViewportLookup(events: ViewportEvent[]): (timestamp: number) => ViewportResolution | undefined {
    if (!events.length) {
        return () => undefined
    }

    const sorted = [...events].sort((a, b) => a.timestamp - b.timestamp)

    return (timestamp: number): ViewportResolution | undefined => {
        let closest: ViewportEvent | undefined
        for (const event of sorted) {
            if (event.timestamp <= timestamp) {
                closest = event
            } else {
                break
            }
        }
        if (!closest) {
            closest = sorted[0]
        }
        return {
            width: String(closest.width),
            height: String(closest.height),
            href: 'unknown',
        }
    }
}

/**
 * Load recording data, process snapshots, build segments, and create
 * one rrweb Replayer per recorded window — but don't start playback.
 *
 * Returns why not when there are no snapshots, or no window has a full snapshot to build a page from.
 */
export async function createReplayers(
    config: PlayerConfig,
    rootEl: HTMLElement,
    bridge: HostBridge
): Promise<ReplayerSetup | ReplayerSetupFailure> {
    const { sources, snapshotsBySource } = await loadAllSources(config, (loaded, total) =>
        bridge.reportLoadingProgress(loaded, total)
    )

    const viewportForTimestamp = buildViewportLookup(config.viewportEvents || [])

    const processingCache: ProcessingCache = { snapshots: {} }
    const snapshots = await processAllSnapshots(
        sources,
        snapshotsBySource,
        processingCache,
        viewportForTimestamp,
        config.sessionId,
        noOpTelemetry
    )

    if (!snapshots.length) {
        return 'no_snapshots'
    }

    const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
    const rawSegments = createSegments(
        snapshots,
        snapshots[0].timestamp,
        snapshots[snapshots.length - 1].timestamp,
        null,
        snapshotsByWindowId
    )
    const segments = mergeInactiveSegments(rawSegments)
    const firstTimestamp = snapshots[0].timestamp
    const windowIds = Object.keys(snapshotsByWindowId).map(Number)
    const keptWindowIds =
        windowIds.length > MAX_REPLAYED_WINDOWS ? busiestWindowIds(segments, MAX_REPLAYED_WINDOWS) : new Set(windowIds)
    const windows: ReplayerWindow[] = []
    for (const [windowId, windowEvents] of Object.entries(snapshotsByWindowId)) {
        if (!keptWindowIds.has(Number(windowId))) {
            continue
        }
        // rrweb cannot build a page without a full snapshot, and its Replayer throws on fewer than two events.
        if (windowEvents.length < 2 || !windowEvents.some((event) => event.type === EventType.FullSnapshot)) {
            continue
        }
        const root = document.createElement('div')
        // Hidden but still laid out: a display:none iframe drops the scroll positions its fast-forward sets.
        root.style.position = 'absolute'
        root.style.inset = '0'
        root.style.visibility = 'hidden'
        rootEl.appendChild(root)
        const replayer = new Replayer(windowEvents, {
            root,
            ...COMMON_REPLAYER_CONFIG,
            insertStyleRules: [
                ...(COMMON_REPLAYER_CONFIG.insertStyleRules || []),
                ...speedDependentStyleRules(config.playbackSpeed),
            ],
            mouseTail: config.mouseTail,
            useVirtualDom: false,
            plugins: [CorsPlugin, HLSPlayerPlugin, AudioMuteReplayerPlugin(true), CanvasReplayerPlugin(windowEvents)],
            speed: config.playbackSpeed,
        })
        windows.push({
            windowId: Number(windowId),
            replayer,
            root,
            initialURL: firstHref(windowEvents),
            firstTimestamp: windowEvents[0].timestamp,
            lastTimestamp: windowEvents[windowEvents.length - 1].timestamp,
        })
    }
    if (!windows.length) {
        return 'no_full_snapshot'
    }
    windows.sort((a, b) => a.firstTimestamp - b.firstTimestamp)

    return { windows, segments, firstTimestamp }
}
