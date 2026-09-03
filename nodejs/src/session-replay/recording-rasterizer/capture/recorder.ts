import type { InactivityPeriod } from '@posthog/replay-headless/protocol'

import { config as defaultConfig } from '~/session-replay/recording-rasterizer/config'
import { RasterizationError } from '~/session-replay/recording-rasterizer/errors'
import { type Logger, createLogger } from '~/session-replay/recording-rasterizer/logger'
import {
    RasterizationProgress,
    RasterizeRecordingInput,
    RecordingResult,
} from '~/session-replay/recording-rasterizer/types'
import { elapsed } from '~/session-replay/recording-rasterizer/utils'

import { BlockProxy } from './block-proxy'
import { BrowserPool } from './browser-pool'
import { capturePlayback } from './capture'
import { CapturePage } from './capture-page'
import { buildCaptureConfig, buildPlayerConfig, validateInput } from './config'
import { PlayerController } from './player'

// Matches the raw frameCaptured count from puppeteer-capture (pre-ffmpeg).
function estimateTotalFrames(
    periods: InactivityPeriod[],
    input: RasterizeRecordingInput,
    playbackSpeed: number,
    captureFps: number
): number {
    const skipInactivity = input.skip_inactivity !== false
    let sessionS: number
    if (skipInactivity) {
        sessionS = periods.filter((p) => p.active).reduce((sum, p) => sum + ((p.ts_to_s ?? 0) - p.ts_from_s), 0)
    } else if (periods.length > 0) {
        sessionS = periods[periods.length - 1].ts_to_s ?? 0
    } else {
        return 0
    }

    if (input.max_virtual_time != null) {
        sessionS = Math.min(sessionS, input.max_virtual_time)
    }

    let videoS = sessionS / playbackSpeed
    if (input.trim != null) {
        videoS = Math.min(videoS, input.trim)
    }

    return Math.max(0, Math.ceil(videoS * captureFps))
}

export interface RasterizeOptions {
    progress?: RasterizationProgress | null
    cfg?: typeof defaultConfig
    log?: Logger
    // Aborting closes the page, which unsticks a pending CDP send and makes the capture loop fail
    // fast, so the browser-pool slot is reclaimed instead of riding out a doomed attempt.
    signal?: AbortSignal
}

export async function rasterizeRecording(
    pool: BrowserPool,
    input: RasterizeRecordingInput,
    outputPath: string,
    playerHtml: string,
    onProgress: () => void,
    options: RasterizeOptions = {}
): Promise<RecordingResult> {
    const progress = options.progress ?? null
    const cfg = options.cfg ?? defaultConfig
    const log = options.log ?? createLogger({ session_id: input.session_id, team_id: input.team_id })
    const signal = options.signal

    validateInput(input)
    signal?.throwIfAborted()

    const setupStart = process.hrtime()
    const captureConfig = buildCaptureConfig(input)

    const rawPage = await pool.getPage()
    const onAbort = (): void => {
        log.warn('abort requested, closing page to stop capture')
        rawPage.close().catch(() => {})
    }
    signal?.addEventListener('abort', onAbort, { once: true })
    let player: PlayerController | null = null
    try {
        // An abort that fired while getPage was launching Chromium predates the listener above and
        // would otherwise be silently missed; the finally below releases the page.
        signal?.throwIfAborted()
        const viewport = {
            width: input.viewport_width || 1280,
            height: input.viewport_height || 720,
        }
        const playerUrl = `${cfg.siteUrl}/player`
        const capturePage = await CapturePage.prepare(
            rawPage,
            viewport,
            playerUrl,
            playerHtml,
            cfg.captureBrowserLogs,
            log
        )

        const blockProxy = new BlockProxy(cfg, log)
        const blockCount = await blockProxy.fetchBlocks(input)
        const compressedBytes = blockProxy.totalCompressedBytes
        log.info({ blockCount, compressedBytes }, 'block listing fetched')
        if (!Number.isFinite(compressedBytes)) {
            // A malformed listing yields NaN, and NaN > cap is false: the gate would switch off
            // silently. Fail open, but visibly.
            log.warn({ blockCount }, 'block listing has non-numeric byte ranges; size gate skipped')
        } else if (compressedBytes > cfg.maxRecordingCompressedBytes) {
            // Fail permanently before loading: oversized recordings run the pod into its memory
            // limit, and the kernel kill takes the healthy renders on the pod down with it.
            throw new RasterizationError(
                `Recording too large to render: ${compressedBytes} compressed bytes in ${blockCount} blocks (limit ${cfg.maxRecordingCompressedBytes})`,
                false,
                'RECORDING_TOO_LARGE'
            )
        }

        const playerConfig = buildPlayerConfig(input, captureConfig.playbackSpeed, blockCount)
        player = new PlayerController(capturePage, blockProxy, onProgress, log)

        log.info('loading player')
        await player.load(playerConfig)
        log.info('player loaded, waiting for recording data')

        await player.waitForStart(playerConfig)
        log.info('recording started')
        onProgress()

        const setupS = elapsed(setupStart)

        if (progress) {
            progress.estimatedTotalFrames = estimateTotalFrames(
                player.getInactivityPeriods(),
                input,
                captureConfig.playbackSpeed,
                captureConfig.captureFps
            )
            progress.phase = 'capture'
            onProgress()
            log.info({ estimated_total_frames: progress.estimatedTotalFrames }, 'estimated capture workload')
        }

        const captureResult = await capturePlayback(player, captureConfig, outputPath, onProgress, progress, log)

        return {
            playback_speed: captureConfig.playbackSpeed,
            capture_duration_s: captureResult.capture_duration_s,
            frame_count: captureResult.frame_count,
            truncated: captureResult.truncated,
            inactivity_periods: captureResult.inactivity_periods,
            timings: { setup_s: setupS, capture_s: captureResult.timings.capture_s },
        }
    } finally {
        signal?.removeEventListener('abort', onAbort)
        player?.dispose()
        await pool.releasePage(rawPage)
    }
}
