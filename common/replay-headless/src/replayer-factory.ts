import { Replayer } from 'posthog-js/rrweb'
import { EventType } from 'posthog-js/rrweb-types'

import {
    AudioMuteReplayerPlugin,
    CanvasReplayerPlugin,
    CorsPlugin,
    COMMON_REPLAYER_CONFIG,
    HLSPlayerPlugin,
    noOpTelemetry,
    processAllSnapshots,
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
 * Returns null if no snapshots are available after processing.
 */
export async function createReplayer(
    config: PlayerConfig,
    rootEl: HTMLElement,
    bridge: HostBridge
): Promise<ReplayerSetup | null> {
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
        return null
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
    const windows: ReplayerWindow[] = []
    for (const [windowId, windowEvents] of Object.entries(snapshotsByWindowId)) {
        // rrweb cannot build a page without a full snapshot, so such a window has nothing to show.
        if (!windowEvents.some((event) => event.type === EventType.FullSnapshot)) {
            continue
        }
        const root = document.createElement('div')
        root.style.display = 'none'
        rootEl.appendChild(root)
        const replayer = new Replayer(windowEvents, {
            root,
            ...COMMON_REPLAYER_CONFIG,
            insertStyleRules: [
                ...(COMMON_REPLAYER_CONFIG.insertStyleRules || []),
                ...(config.playbackSpeed >= 2
                    ? ['*, *::before, *::after { animation: none !important; transition: none !important; }']
                    : []),
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
            initialURL: windowEvents.map(getHrefFromSnapshot).find(Boolean) ?? '',
            firstTimestamp: windowEvents[0].timestamp,
        })
    }
    if (!windows.length) {
        return null
    }
    windows.sort((a, b) => a.firstTimestamp - b.firstTimestamp)

    return { windows, segments, firstTimestamp }
}
