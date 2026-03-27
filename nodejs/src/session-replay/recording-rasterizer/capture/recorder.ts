import { config as defaultConfig } from '../config'
import { type Logger, createLogger } from '../logger'
import { RasterizeRecordingInput, RecordingResult } from '../types'
import { elapsed } from '../utils'
import { BlockProxy } from './block-proxy'
import { BrowserPool } from './browser-pool'
import { capturePlayback } from './capture'
import { CapturePage } from './capture-page'
import { buildCaptureConfig, buildPlayerConfig, validateInput } from './config'
import { PlayerController } from './player'

export async function rasterizeRecording(
    pool: BrowserPool,
    input: RasterizeRecordingInput,
    outputPath: string,
    playerHtml: string,
    cfg: typeof defaultConfig = defaultConfig,
    log: Logger = createLogger({ session_id: input.session_id, team_id: input.team_id }),
    onProgress?: () => void
): Promise<RecordingResult> {
    validateInput(input)

    const setupStart = process.hrtime()
    const captureConfig = buildCaptureConfig(input)

    const rawPage = await pool.getPage()
    let player: PlayerController | null = null
    try {
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
        log.info({ blockCount }, 'block listing fetched')

        const playerConfig = buildPlayerConfig(input, captureConfig.playbackSpeed, blockCount)
        player = new PlayerController(capturePage, blockProxy, log)

        log.info('loading player')
        await player.load(playerConfig)
        log.info('player loaded, waiting for recording data')

        await player.waitForStart(playerConfig)
        log.info('recording started')
        onProgress?.()

        const setupS = elapsed(setupStart)

        const captureResult = await capturePlayback(player, captureConfig, outputPath, log, onProgress)

        return {
            video_path: outputPath,
            playback_speed: captureConfig.playbackSpeed,
            capture_duration_s: captureResult.capture_duration_s,
            frame_count: captureResult.frame_count,
            truncated: captureResult.truncated,
            inactivity_periods: captureResult.inactivity_periods,
            custom_fps: captureConfig.outputFps,
            timings: { setup_s: setupS, capture_s: captureResult.timings.capture_s },
        }
    } finally {
        player?.dispose()
        await pool.releasePage(rawPage)
    }
}
