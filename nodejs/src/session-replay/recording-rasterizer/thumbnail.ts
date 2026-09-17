import { execFile } from 'child_process'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'
import { promisify } from 'util'

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

/**
 * Cut one frame from an already-rendered analysis MP4 and store it as a PNG.
 *
 * No browser, so this costs seconds of CPU rather than a recording load. The crop removes the
 * burned-in metadata footer, which is an artifact of the analysis render and not part of the page.
 */
export async function extractThumbnail(input: ExtractThumbnailInput): Promise<ExtractThumbnailOutput> {
    const source = parseS3Uri(input.source_s3_uri)
    const workDir = await fs.mkdtemp(path.join(process.env.VIDEO_WORK_DIR || os.tmpdir(), 'thumb-'))
    const sourcePath = path.join(workDir, 'source.mp4')
    const outputPath = path.join(workDir, 'thumbnail.png')

    try {
        await downloadFromS3(source.bucket, source.key, sourcePath)

        const footer = Math.max(0, Math.floor(input.footer_crop_px ?? 0))
        const width = Math.max(1, Math.floor(input.width ?? 1280))
        // crop before scale: the footer is measured in source pixels.
        const filters = [`crop=iw:ih-${footer}:0:0`, `scale=${width}:-2`].join(',')

        // -ss before -i seeks by keyframe index rather than decoding to the timestamp, which is what
        // keeps this cheap. -frames:v 1 stops after the first frame it lands on.
        const args = [
            '-nostdin',
            '-loglevel',
            'error',
            '-ss',
            String(Math.max(0, input.video_time_s)),
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
