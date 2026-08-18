import { Replayer } from 'posthog-js/rrweb'
import { EventType, type eventWithTime } from 'posthog-js/rrweb-types'

import {
    AudioMuteReplayerPlugin,
    CanvasReplayerPlugin,
    CorsPlugin,
    COMMON_REPLAYER_CONFIG,
    highSpeedAnimationStyleRules,
    HLSPlayerPlugin,
    noOpTelemetry,
    processAllSnapshots,
    createSegments,
    mapSnapshotsToWindowId,
    mergeInactiveSegments,
    type ProcessingCache,
    type RecordingSegment,
    type ViewportResolution,
} from '@posthog/replay-shared'

import { loadAllSources } from './data-loader'
import type { HostBridge } from './host-bridge'
import type { PlayerConfig, ViewportEvent } from './types'

/** Extract the page URL from an rrweb Meta event, if present. */
export function getMetaHref(event: eventWithTime): string | undefined {
    if (event.type === EventType.Meta) {
        return (event.data as { href?: string })?.href
    }
    return undefined
}

/** Extract the recorded viewport size from an rrweb Meta event, if present. */
function getMetaResolution(event: eventWithTime): { width: number; height: number } | undefined {
    if (event.type === EventType.Meta) {
        const data = event.data as { width?: number; height?: number }
        if (data?.width && data?.height) {
            return { width: data.width, height: data.height }
        }
    }
    return undefined
}

export interface ReplayerSetup {
    replayer: Replayer
    events: eventWithTime[]
    segments: RecordingSegment[]
    firstTimestamp: number
    initialURL: string
    initialResolution?: { width: number; height: number }
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
 * an rrweb Replayer — but don't start playback.
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
    const events: eventWithTime[] = [...snapshots]

    const replayer = new Replayer(events, {
        root: rootEl,
        ...COMMON_REPLAYER_CONFIG,
        insertStyleRules: [
            ...(COMMON_REPLAYER_CONFIG.insertStyleRules || []),
            ...highSpeedAnimationStyleRules(config.playbackSpeed),
        ],
        mouseTail: config.mouseTail,
        useVirtualDom: false,
        plugins: [CorsPlugin, HLSPlayerPlugin, AudioMuteReplayerPlugin(true), CanvasReplayerPlugin(events)],
        speed: config.playbackSpeed,
    })

    let initialURL = ''
    let initialResolution: { width: number; height: number } | undefined
    for (const e of events) {
        if (!initialURL) {
            initialURL = getMetaHref(e) ?? ''
        }
        if (!initialResolution) {
            initialResolution = getMetaResolution(e)
        }
        if (initialURL && initialResolution) {
            break
        }
    }

    return { replayer, events, segments, firstTimestamp, initialURL, initialResolution }
}
