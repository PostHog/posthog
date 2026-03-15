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
    type ProcessingCache,
    type ViewportResolution,
} from '@posthog/replay-shared'
import { Replayer } from '@posthog/rrweb'
import type { eventWithTime } from '@posthog/rrweb-types'

import { loadAllSources } from './data-loader'
import { publishSegments, createSegmentTracker, signalRecordingEnded } from './segment-tracker'
import type { PlayerConfig, ViewportEvent } from './types'

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

async function init(config: PlayerConfig): Promise<void> {
    const { sources, snapshotsBySource } = await loadAllSources(config)
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
        console.error('[headless-player] No snapshots after processing')
        signalRecordingEnded()
        return
    }

    const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
    const segments = createSegments(
        snapshots,
        snapshots[0].timestamp,
        snapshots[snapshots.length - 1].timestamp,
        null,
        snapshotsByWindowId
    )

    publishSegments(segments)
    const trackSegment = createSegmentTracker(segments)

    const events: eventWithTime[] = snapshots

    const replayer = new Replayer(events, {
        root: document.querySelector('.PlayerFrame__content') as HTMLElement,
        ...COMMON_REPLAYER_CONFIG,
        insertStyleRules: [
            ...(COMMON_REPLAYER_CONFIG.insertStyleRules || []),
            ...(config.playbackSpeed >= 2
                ? ['*, *::before, *::after { animation: none !important; transition: none !important; }']
                : []),
        ],
        mouseTail: config.mouseTail,
        skipInactive: config.skipInactivity,
        useVirtualDom: false,
        plugins: [
            CorsPlugin,
            HLSPlayerPlugin,
            AudioMuteReplayerPlugin(true),
            CanvasReplayerPlugin(events),
            {
                handler: (_event: eventWithTime, isSync: boolean) => {
                    if (!isSync) {
                        trackSegment(_event.timestamp)
                    }
                },
            },
        ],
        speed: config.playbackSpeed,
    })

    replayer.on('finish', () => {
        signalRecordingEnded()
    })

    replayer.on('resize', (dimension: { width: number; height: number }) => {
        const viewportWidth = window.innerWidth
        const viewportHeight = window.innerHeight
        const scale = Math.min(viewportWidth / dimension.width, viewportHeight / dimension.height)
        replayer.wrapper.style.transform = `scale(${scale})`
    })

    if (config.endTimestamp) {
        const endTs = config.endTimestamp
        replayer.on('event-cast', (event: eventWithTime) => {
            if (event.timestamp >= endTs) {
                replayer.pause()
                signalRecordingEnded()
            }
        })
    }

    const startOffset = config.startTimestamp ? config.startTimestamp - snapshots[0].timestamp : 0
    replayer.play(Math.max(0, startOffset))
}

window.addEventListener('posthog-player-init', () => {
    const config = window.__POSTHOG_PLAYER_CONFIG__
    if (!config) {
        console.error('[headless-player] No config on window.__POSTHOG_PLAYER_CONFIG__')
        signalRecordingEnded()
        return
    }

    init(config).catch((err) => {
        console.error('[headless-player] Fatal error:', err instanceof Error ? err.message : JSON.stringify(err))
        signalRecordingEnded()
    })
})
