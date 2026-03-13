import { execFile } from 'child_process'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)

export interface PostProcessOptions {
    inputPath: string
    outputPath: string
    preRoll: number
    recordingDuration: number
    playbackSpeed: number
    customFps: number | null
}

function buildVideoFilter(playbackSpeed: number, fpsToRenderAt: number | null): string | null {
    const parts: string[] = []
    if (playbackSpeed > 1) {
        parts.push(`setpts=${playbackSpeed}*PTS`)
    }
    if (fpsToRenderAt) {
        parts.push(`fps=${fpsToRenderAt}`)
    }
    return parts.length > 0 ? parts.join(',') : null
}

function computeOutputFps(customFps: number | null, playbackSpeed: number): number | null {
    if (customFps && playbackSpeed > 1) {
        return Math.floor(customFps / playbackSpeed)
    }
    return customFps || null
}

export async function postProcessToMp4(opts: PostProcessOptions): Promise<void> {
    const fpsToRenderAt = computeOutputFps(opts.customFps, opts.playbackSpeed)
    const videoFilter = buildVideoFilter(opts.playbackSpeed, fpsToRenderAt)
    const ffmpegPath = process.env.FFMPEG_PATH || 'ffmpeg'

    const args = [
        '-hide_banner',
        '-loglevel',
        'error',
        '-y',
        '-ss',
        opts.preRoll.toFixed(2),
        '-i',
        opts.inputPath,
        '-t',
        opts.recordingDuration.toFixed(2),
        '-c:v',
        'libx264',
        '-preset',
        'veryfast',
        '-crf',
        '23',
        '-pix_fmt',
        'yuv420p',
        '-movflags',
        '+faststart',
        '-f',
        'mp4',
    ]

    if (videoFilter) {
        args.push('-vf', videoFilter)
    }

    args.push(opts.outputPath)

    try {
        await execFileAsync(ffmpegPath, args, { timeout: 600_000 })
    } catch (err: any) {
        const stderr = err.stderr?.trim() || ''
        throw new Error(`ffmpeg failed with exit code ${err.code}${stderr ? `: ${stderr}` : ''}`)
    }
}
