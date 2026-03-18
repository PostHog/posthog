import * as activity from '@temporalio/activity'
import { randomUUID } from 'crypto'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'

import { BrowserPool } from './browser-pool'
import { postProcessToMp4 } from './postprocess'
import { rasterizeRecording } from './recorder'
import { uploadToS3 } from './storage'
import { RasterizeRecordingInput, RasterizeRecordingOutput } from './types'

let browserPool: BrowserPool | null = null

export function setBrowserPool(pool: BrowserPool): void {
    browserPool = pool
}

export async function rasterizeRecordingActivity(input: RasterizeRecordingInput): Promise<RasterizeRecordingOutput> {
    if (!browserPool) {
        throw new Error('Browser pool not initialized — call setBrowserPool() before running activities')
    }

    const id = randomUUID()
    const workDir = process.env.VIDEO_WORK_DIR || os.tmpdir()
    const tmpFile = (label: string) => path.join(workDir, `ph-video-${label}-${id}.mp4`)
    const rawPath = tmpFile('raw')
    const processedPath = tmpFile('out')

    try {
        const result = await rasterizeRecording(browserPool, input, rawPath)

        if (!input.skip_postprocessing) {
            await postProcessToMp4({
                inputPath: rawPath,
                outputPath: processedPath,
                preRoll: result.pre_roll,
                recordingDuration: input.recording_duration,
                playbackSpeed: result.playback_speed,
                customFps: result.custom_fps,
            })
        }

        const videoPath = input.skip_postprocessing ? rawPath : processedPath
        const activityId = activity.Context.current().info.activityId
        const s3Key = await uploadToS3(videoPath, input.s3_bucket, input.s3_key_prefix, activityId)
        const stat = await fs.stat(videoPath)

        return {
            s3_key: s3Key,
            pre_roll: result.pre_roll,
            playback_speed: result.playback_speed,
            measured_width: result.measured_width,
            inactivity_periods: result.inactivity_periods,
            segment_start_timestamps: result.segment_start_timestamps,
            custom_fps: result.custom_fps,
            file_size_bytes: stat.size,
        }
    } finally {
        await Promise.all([fs.rm(rawPath, { force: true }), fs.rm(processedPath, { force: true })])
    }
}
