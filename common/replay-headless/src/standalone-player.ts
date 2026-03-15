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
import type { eventWithTime } from '@posthog/rrweb-types'

import { DataLoadError, loadAllSources } from './data-loader'
import { publishSegments, createSegmentTracker, signalRecordingStarted, signalRecordingEnded } from './segment-tracker'
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
    // --- Load and process snapshots ---

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
        window.__POSTHOG_PLAYER_ERROR__ = {
            code: 'NO_SNAPSHOTS',
            message: 'No snapshots after processing',
            retryable: true,
        }
        signalRecordingEnded()
        return
    }

    // --- Build segments and prepare events ---

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
    const events = [...snapshots]

    // --- Set up segment tracking ---

    const trackSegment = createSegmentTracker(segments, firstTimestamp)
    let stopped = false

    // --- Create replayer ---

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
        useVirtualDom: false,
        plugins: [
            CorsPlugin,
            HLSPlayerPlugin,
            AudioMuteReplayerPlugin(true),
            CanvasReplayerPlugin(events),
            {
                handler: (event: eventWithTime, isSync: boolean) => {
                    if (!isSync) {
                        trackSegment(event.timestamp)
                    }
                },
            },
        ],
        speed: config.playbackSpeed,
    })

    // Skip inactive segments by polling the current playback position each
    // frame. Under puppeteer-capture's virtual time, rAF fires once per
    // beginFrame call, so this is deterministic.
    if (config.skipInactivity) {
        const checkAndSkip = (): void => {
            if (stopped) {
                return
            }
            const ts = firstTimestamp + replayer.getCurrentTime()
            const inactiveSeg = segments.find(
                (seg: RecordingSegment) => !seg.isActive && ts >= seg.startTimestamp && ts < seg.endTimestamp
            )
            if (inactiveSeg) {
                replayer.play(inactiveSeg.endTimestamp - firstTimestamp)
            }
            requestAnimationFrame(checkAndSkip)
        }
        requestAnimationFrame(checkAndSkip)
    }

    // --- Resolution tracking and viewport scaling ---

    const contentEl = document.querySelector('.PlayerFrame__content') as HTMLElement
    const footerHeight = config.showMetadataFooter ? 32 : 0

    function applyScale(recWidth: number, recHeight: number): void {
        const availW = window.innerWidth
        const availH = window.innerHeight - footerHeight
        if (recWidth <= 0 || recHeight <= 0 || availW <= 0 || availH <= 0) {
            return
        }
        const scale = Math.min(availW / recWidth, availH / recHeight)
        const scaledW = recWidth * scale
        const scaledH = recHeight * scale
        const offsetX = (availW - scaledW) / 2
        const offsetY = (availH - scaledH) / 2
        // Clip the content element to the recording's native size, then
        // scale it down and center within the available space.
        contentEl.style.width = `${recWidth}px`
        contentEl.style.height = `${recHeight}px`
        contentEl.style.overflow = 'hidden'
        contentEl.style.transformOrigin = 'top left'
        contentEl.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`
        window.__POSTHOG_RESOLUTION__ = { width: recWidth, height: recHeight }
    }

    const iframeWidth = Number.parseFloat(replayer.iframe.width)
    const iframeHeight = Number.parseFloat(replayer.iframe.height)
    if (iframeWidth > 0 && iframeHeight > 0) {
        applyScale(iframeWidth, iframeHeight)
    }

    replayer.on('resize', (dimension: { width: number; height: number }) => {
        applyScale(dimension.width, dimension.height)
    })

    // --- End conditions ---

    replayer.on('finish', () => {
        stopped = true
        signalRecordingEnded()
    })

    if (config.endTimestamp) {
        const endTs = config.endTimestamp
        replayer.on('event-cast', (event: eventWithTime) => {
            if (event.timestamp >= endTs) {
                stopped = true
                replayer.pause()
                signalRecordingEnded()
            }
        })
    }

    // --- Metadata footer ---

    let currentURL = ''
    replayer.on('event-cast', (event: eventWithTime) => {
        if (event.type === 4 && (event.data as any)?.href) {
            currentURL = (event.data as any).href
        }
    })

    const footerEl = document.getElementById('metadata-footer')
    const metaUrlEl = document.getElementById('meta-url')
    const metaRectEl = document.getElementById('meta-rect')
    const metaStatusEl = document.getElementById('meta-status')

    if (config.showMetadataFooter && footerEl) {
        footerEl.style.display = 'flex'

        const updateFooter = (): void => {
            if (!metaUrlEl || !metaRectEl || !metaStatusEl) {
                return
            }
            metaUrlEl.textContent = currentURL
            metaRectEl.textContent = (replayer.getCurrentTime() / 1000).toFixed(0)

            if (stopped) {
                metaStatusEl.className = 'status-ended'
                metaStatusEl.textContent = '[RECORDING ENDED]'
            } else {
                const ts = firstTimestamp + replayer.getCurrentTime()
                const isIdle = segments.some(
                    (seg) => !seg.isActive && ts >= seg.startTimestamp && ts <= seg.endTimestamp
                )
                if (isIdle) {
                    metaStatusEl.className = 'status-idle'
                    metaStatusEl.textContent = '[IDLE]'
                } else {
                    metaStatusEl.className = ''
                    metaStatusEl.textContent = ''
                }
            }
        }

        const onFrame = (): void => {
            updateFooter()
            if (!stopped) {
                requestAnimationFrame(onFrame)
            }
        }
        requestAnimationFrame(onFrame)
    }

    // --- Signal ready and start playback ---
    // Publish segments last — if anything above threw (e.g. Replayer
    // construction), segments are never published and the recorder
    // correctly times out instead of capturing a broken page.

    publishSegments(segments, firstTimestamp)
    signalRecordingStarted()

    const startOffset = config.startTimestamp ? config.startTimestamp - snapshots[0].timestamp : 0
    await new Promise<void>((resolve) => {
        window.addEventListener('posthog-player-start', () => resolve(), { once: true })
    })
    replayer.play(Math.max(0, startOffset))
}

window.addEventListener('posthog-player-init', () => {
    const config = window.__POSTHOG_PLAYER_CONFIG__
    if (!config) {
        console.error('[headless-player] No config on window.__POSTHOG_PLAYER_CONFIG__')
        window.__POSTHOG_PLAYER_ERROR__ = { code: 'NO_CONFIG', message: 'No player config provided', retryable: false }
        signalRecordingEnded()
        return
    }

    init(config).catch((err) => {
        const message = err instanceof Error ? err.message : String(err)
        const retryable = err instanceof DataLoadError ? err.retryable : true
        const code = err instanceof DataLoadError ? 'DATA_LOAD_FAILED' : 'INIT_FAILED'
        console.error('[headless-player] Fatal error:', message)
        window.__POSTHOG_PLAYER_ERROR__ = { code, message, retryable }
        signalRecordingEnded()
    })
})
