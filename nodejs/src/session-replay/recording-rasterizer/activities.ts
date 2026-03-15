import { ApplicationFailure } from '@temporalio/common'
import { randomUUID } from 'crypto'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'

import { BrowserPool } from './browser-pool'
import { RasterizationError } from './errors'
import { RasterizationMetrics } from './metrics'
import { computeVideoTimestamps } from './postprocess'
import { rasterizeRecording } from './recorder'
import { uploadToS3 } from './storage'
import { ActivityTimings, RasterizeRecordingInput, RasterizeRecordingOutput } from './types'
import { elapsed } from './utils'

function toActivityError(err: unknown): Error {
    if (err instanceof RasterizationError && !err.retryable) {
        return ApplicationFailure.nonRetryable(err.message, 'NON_RETRYABLE', err)
    }
    return err instanceof Error ? err : new Error(String(err))
}

let browserPool: BrowserPool | null = null

export function setBrowserPool(pool: BrowserPool): void {
    browserPool = pool
}

export async function rasterizeRecordingActivity(input: RasterizeRecordingInput): Promise<RasterizeRecordingOutput> {
    if (!browserPool) {
        throw new Error('Browser pool not initialized — call setBrowserPool() before running activities')
    }

    const { activePages } = browserPool.stats
    console.log(`[rasterizer] Starting activity for session=${input.session_id} (active pages: ${activePages})`)

    const activityStart = process.hrtime()
    const id = randomUUID()
    const workDir = process.env.VIDEO_WORK_DIR || os.tmpdir()
    const outputPath = path.join(workDir, `ph-video-${id}.mp4`)

    const timings: ActivityTimings = { total_s: 0, setup_s: 0, capture_s: 0, upload_s: 0 }

    try {
        const result = await rasterizeRecording(browserPool, input, outputPath)
        timings.setup_s = result.timings.setup_s
        timings.capture_s = result.timings.capture_s
        RasterizationMetrics.observeSetup('success', timings.setup_s)
        RasterizationMetrics.observeCapture('success', timings.capture_s)

        // Compute video-time positions for each inactivity period
        const periods = computeVideoTimestamps(result.inactivity_periods)

        const uploadStart = process.hrtime()
        const s3Uri = await uploadToS3(outputPath, input.s3_bucket, input.s3_key_prefix, id)
        timings.upload_s = elapsed(uploadStart)
        RasterizationMetrics.observeUpload('success', timings.upload_s)

        const stat = await fs.stat(outputPath)
        timings.total_s = elapsed(activityStart)
        RasterizationMetrics.observeActivity('success', timings.total_s)

        return {
            s3_uri: s3Uri,
            video_duration_s: Math.round(result.capture_duration_s),
            playback_speed: result.playback_speed,
            show_metadata_footer: !!input.show_metadata_footer,
            inactivity_periods: periods,
            file_size_bytes: stat.size,
            timings,
        }
    } catch (err) {
        timings.total_s = elapsed(activityStart)
        RasterizationMetrics.observeActivity('error', timings.total_s)
        throw toActivityError(err)
    } finally {
        await fs.rm(outputPath, { force: true })
    }
}
