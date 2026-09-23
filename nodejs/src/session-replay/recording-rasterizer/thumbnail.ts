import { execFile } from 'child_process'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'
import { promisify } from 'util'

import { toFiniteNumber } from './capture/config'
import { RasterizationError } from './errors'
import { createLogger } from './logger'
import { downloadFromS3, uploadToS3 } from './storage'
import type { ExtractThumbnailInput, ExtractThumbnailOutput } from './types'

const execFileAsync = promisify(execFile)
const log = createLogger()

// One frame out of an existing MP4 never approaches the render timeouts; a longer wait means ffmpeg
// is wedged on a corrupt file rather than working.
const FFMPEG_TIMEOUT_MS = 60_000

function parseS3Uri(uri: string): { bucket: string; key: string } {
    const match = /^s3:\/\/([^/]+)\/(.+)$/.exec(uri)
    if (!match) {
        throw new RasterizationError(`Not an S3 URI: ${uri}`, false, 'INVALID_INPUT')
    }
    return { bucket: match[1], key: match[2] }
}

export interface Rect {
    w: number
    h: number
    x: number
    y: number
}

const BORDER_TOLERANCE = 6
// Every 8th row/column is enough to tell a uniform bar from page content, and keeps the scan cheap.
const SCAN_STEP = 8

function matchesBorder(frame: Buffer, offset: number, r: number, g: number, b: number): boolean {
    return (
        Math.abs(frame[offset] - r) <= BORDER_TOLERANCE &&
        Math.abs(frame[offset + 1] - g) <= BORDER_TOLERANCE &&
        Math.abs(frame[offset + 2] - b) <= BORDER_TOLERANCE
    )
}

/** The page inside the analysis canvas, when a phone-sized session leaves a uniform border around it. */
// Corner colour rather than a luma threshold: the background is not black, so cropdetect misses it, and
// a threshold high enough to catch it crops into a dark page.
export function uniformBorderRect(frame: Buffer, width: number, height: number): Rect | null {
    if (frame.length < width * height * 3) {
        return null
    }
    const [r, g, b] = [frame[0], frame[1], frame[2]]
    const at = (x: number, y: number): number => (y * width + x) * 3

    const columnIsBorder = (x: number): boolean => {
        for (let y = 0; y < height; y += SCAN_STEP) {
            if (!matchesBorder(frame, at(x, y), r, g, b)) {
                return false
            }
        }
        return true
    }
    const rowIsBorder = (y: number): boolean => {
        for (let x = 0; x < width; x += SCAN_STEP) {
            if (!matchesBorder(frame, at(x, y), r, g, b)) {
                return false
            }
        }
        return true
    }

    let left = 0
    while (left < width && columnIsBorder(left)) {
        left++
    }
    if (left === width) {
        // A frame of nothing but border: the render is blank, so there is no page to find.
        return null
    }
    let right = width - 1
    while (right > left && columnIsBorder(right)) {
        right--
    }
    let top = 0
    while (top < height && rowIsBorder(top)) {
        top++
    }
    let bottom = height - 1
    while (bottom > top && rowIsBorder(bottom)) {
        bottom--
    }

    const rect = { w: right - left + 1, h: bottom - top + 1, x: left, y: top }
    if (rect.w < width * 0.1 || rect.h < height * 0.1) {
        return null
    }
    // Worth a second ffmpeg pass only when it removes a real share of the frame.
    if (1 - (rect.w * rect.h) / (width * height) < 0.15) {
        return null
    }
    return rect
}

async function frameSize(sourcePath: string): Promise<{ width: number; height: number } | null> {
    try {
        const { stdout } = await execFileAsync(
            'ffprobe',
            [
                '-v',
                'error',
                '-select_streams',
                'v:0',
                '-show_entries',
                'stream=width,height',
                '-of',
                'csv=p=0',
                sourcePath,
            ],
            { timeout: FFMPEG_TIMEOUT_MS }
        )
        const [width, height] = stdout.trim().split(',').map(Number)
        return Number.isFinite(width) && Number.isFinite(height) ? { width, height } : null
    } catch (err) {
        log.warn({ err: (err as Error)?.message }, 'ffprobe could not read the frame size')
        return null
    }
}

async function detectBorder(
    sourcePath: string,
    rawPath: string,
    videoTimeS: number,
    footerCrop: string,
    width: number,
    height: number
): Promise<Rect | null> {
    try {
        await execFileAsync(
            'ffmpeg',
            [
                '-nostdin',
                '-loglevel',
                'error',
                '-ss',
                String(videoTimeS),
                '-i',
                sourcePath,
                '-frames:v',
                '1',
                '-vf',
                footerCrop,
                '-pix_fmt',
                'rgb24',
                '-f',
                'rawvideo',
                '-y',
                rawPath,
            ],
            { timeout: FFMPEG_TIMEOUT_MS }
        )
        return uniformBorderRect(await fs.readFile(rawPath), width, height)
    } catch (err) {
        // Best-effort: a failed probe means the full frame, never a failed thumbnail.
        log.warn({ err: (err as Error)?.message }, 'border detection failed, keeping the full frame')
        return null
    }
}

/**
 * Cut one frame from an already-rendered analysis MP4 and store it as a PNG.
 *
 * No browser, so this costs seconds of CPU rather than a recording load. The crop removes the
 * burned-in metadata footer, which is an artifact of the analysis render and not part of the page.
 */
export async function extractThumbnail(input: ExtractThumbnailInput): Promise<ExtractThumbnailOutput> {
    const source = parseS3Uri(input.source_s3_uri)
    // Before the download: `-ss NaN` burns both attempts, each pulling the whole MP4 first.
    const videoTimeS = Math.max(0, toFiniteNumber(input.video_time_s, 'video_time_s'))
    const workDir = await fs.mkdtemp(path.join(process.env.VIDEO_WORK_DIR || os.tmpdir(), 'thumb-'))
    const sourcePath = path.join(workDir, 'source.mp4')
    const outputPath = path.join(workDir, 'thumbnail.png')
    const rawPath = path.join(workDir, 'frame.rgb')

    try {
        await downloadFromS3(source.bucket, source.key, sourcePath)

        const footer = Math.max(0, Math.floor(input.footer_crop_px ?? 0))
        const width = Math.max(1, Math.floor(input.width ?? 1280))
        // crop before scale: the footer is measured in source pixels.
        const footerCrop = `crop=iw:ih-${footer}:0:0`

        const size = await frameSize(sourcePath)
        const letterbox = size
            ? await detectBorder(sourcePath, rawPath, videoTimeS, footerCrop, size.width, size.height - footer)
            : null
        if (letterbox) {
            log.info({ ...letterbox, frame: size }, 'cropping the letterbox around the page')
        }

        const crops = letterbox
            ? [footerCrop, `crop=${letterbox.w}:${letterbox.h}:${letterbox.x}:${letterbox.y}`]
            : [footerCrop]
        // Never upscale: a phone-sized page stretched to 1280 is a blurrier, heavier poster.
        const sourceWidth = letterbox?.w ?? size?.width ?? width
        const filters = [...crops, `scale=${Math.min(width, sourceWidth)}:-2`].join(',')

        // -ss before -i seeks by keyframe index rather than decoding to the timestamp, which is what
        // keeps this cheap. -frames:v 1 stops after the first frame it lands on.
        const args = [
            '-nostdin',
            '-loglevel',
            'error',
            '-ss',
            String(videoTimeS),
            '-i',
            sourcePath,
            '-frames:v',
            '1',
            '-vf',
            filters,
            '-y',
            outputPath,
        ]

        try {
            await execFileAsync('ffmpeg', args, { timeout: FFMPEG_TIMEOUT_MS })
        } catch (err) {
            const stderr = (err as { stderr?: string })?.stderr?.slice(0, 500) ?? ''
            log.warn({ err: (err as Error)?.message, stderr }, 'thumbnail extraction failed')
            throw new RasterizationError(
                `ffmpeg could not extract a frame: ${(err as Error)?.message ?? String(err)}`,
                true,
                'THUMBNAIL_EXTRACT_FAILED',
                err
            )
        }

        const stat = await fs.stat(outputPath).catch(() => null)
        if (!stat || stat.size === 0) {
            // A seek past the end of the video exits 0 and writes nothing, so size is the real check.
            throw new RasterizationError(
                `ffmpeg wrote no frame at ${input.video_time_s}s`,
                false,
                'THUMBNAIL_EMPTY_OUTPUT'
            )
        }

        const s3Uri = await uploadToS3(outputPath, input.s3_bucket, input.s3_key_prefix, input.id, 'png')
        return { s3_uri: s3Uri, file_size_bytes: stat.size }
    } finally {
        await fs.rm(workDir, { recursive: true, force: true })
    }
}
