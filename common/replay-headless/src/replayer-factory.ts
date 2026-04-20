import {
    AudioMuteReplayerPlugin,
    CanvasReplayerPlugin,
    CorsPlugin,
    COMMON_REPLAYER_CONFIG,
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
import { Replayer } from '@posthog/rrweb'
import { EventType, type eventWithTime } from '@posthog/rrweb-types'

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

export interface ReplayerSetup {
    replayer: Replayer
    events: eventWithTime[]
    segments: RecordingSegment[]
    firstTimestamp: number
    initialURL: string
}

/**
 * Thrown when rrweb can't build the DOM for a recording — for example because
 * the captured page contains a non-spec tag (`<webview>`) that triggers a
 * DOMException from `customElements.define` during node reconstruction. These
 * are not retryable: the recording itself is malformed.
 */
export class InvalidRecordingError extends Error {
    readonly cause: unknown

    constructor(message: string, cause: unknown) {
        super(message)
        this.name = 'InvalidRecordingError'
        this.cause = cause
    }
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

    let replayer: Replayer
    try {
        replayer = new Replayer(events, {
            root: rootEl,
            ...COMMON_REPLAYER_CONFIG,
            insertStyleRules: [
                ...(COMMON_REPLAYER_CONFIG.insertStyleRules || []),
                ...(config.playbackSpeed >= 2
                    ? ['*, *::before, *::after { animation: none !important; transition: none !important; }']
                    : []),
            ],
            mouseTail: config.mouseTail,
            useVirtualDom: false,
            plugins: [CorsPlugin, HLSPlayerPlugin, AudioMuteReplayerPlugin(true), CanvasReplayerPlugin(events)],
            speed: config.playbackSpeed,
        })
    } catch (err) {
        // rrweb throws synchronously when the snapshot contains a non-spec tag
        // like <webview> that fails customElements.define. Surface as a typed,
        // non-retryable error so callers can classify it separately from transient
        // init failures.
        const message = err instanceof Error ? err.message : String(err)
        throw new InvalidRecordingError(`Failed to build replayer from snapshots: ${message}`, err)
    }

    let initialURL = ''
    for (const e of events) {
        const href = getMetaHref(e)
        if (href) {
            initialURL = href
            break
        }
    }

    return { replayer, events, segments, firstTimestamp, initialURL }
}
