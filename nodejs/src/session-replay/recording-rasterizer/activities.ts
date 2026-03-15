import { Context } from '@temporalio/activity'
import { ApplicationFailure } from '@temporalio/common'
import { randomUUID } from 'crypto'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'

import { BrowserPool } from './browser-pool'
import { RasterizationError } from './errors'
import { createLogger } from './logger'
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

async function rasterizeRecordingActivity(
    pool: BrowserPool,
    input: RasterizeRecordingInput
): Promise<RasterizeRecordingOutput> {
    const { workflowExecution, activityId } = Context.current().info
    const log = createLogger({
        session_id: input.session_id,
        team_id: input.team_id,
        workflow_id: workflowExecution.workflowId,
        activity_id: activityId,
    })
    const { activePages } = pool.stats
    log.info({ active_pages: activePages }, 'starting activity')

    const activityStart = process.hrtime()
    const id = randomUUID()
    const workDir = process.env.VIDEO_WORK_DIR || os.tmpdir()
    const outputPath = path.join(workDir, `ph-video-${id}.mp4`)

    const timings: ActivityTimings = { total_s: 0, setup_s: 0, capture_s: 0, upload_s: 0 }

    try {
        const result = await rasterizeRecording(pool, input, outputPath, undefined, log)
        timings.setup_s = result.timings.setup_s
        timings.capture_s = result.timings.capture_s
        RasterizationMetrics.observeSetup('success', timings.setup_s)
        RasterizationMetrics.observeCapture('success', timings.capture_s)

        const periods = computeVideoTimestamps(result.inactivity_periods)

        const uploadStart = process.hrtime()
        const s3Uri = await uploadToS3(outputPath, input.s3_bucket, input.s3_key_prefix, id)
        timings.upload_s = elapsed(uploadStart)
        RasterizationMetrics.observeUpload('success', timings.upload_s)

        const stat = await fs.stat(outputPath)
        timings.total_s = elapsed(activityStart)
        RasterizationMetrics.observeActivity('success', timings.total_s)

        const output: RasterizeRecordingOutput = {
            s3_uri: s3Uri,
            video_duration_s: Math.round(result.capture_duration_s),
            playback_speed: result.playback_speed,
            show_metadata_footer: !!input.show_metadata_footer,
            inactivity_periods: periods,
            file_size_bytes: stat.size,
            timings,
        }

        log.info(
            {
                s3_uri: output.s3_uri,
                video_duration_s: output.video_duration_s,
                playback_speed: output.playback_speed,
                file_size_bytes: output.file_size_bytes,
                timings: output.timings,
            },
            'activity complete'
        )

        return output
    } catch (err) {
        timings.total_s = elapsed(activityStart)
        RasterizationMetrics.observeActivity('error', timings.total_s)
        throw toActivityError(err)
    } finally {
        await fs.rm(outputPath, { force: true })
    }
}

export function createActivities(pool: BrowserPool) {
    return {
        'rasterize-recording': (input: RasterizeRecordingInput) => rasterizeRecordingActivity(pool, input),
    }
}
