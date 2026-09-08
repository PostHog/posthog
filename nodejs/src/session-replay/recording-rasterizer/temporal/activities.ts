import { Context } from '@temporalio/activity'
import { ApplicationFailure } from '@temporalio/common'
import { randomUUID } from 'crypto'
import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'

import { BrowserPool } from '~/session-replay/recording-rasterizer/capture/browser-pool'
import { rasterizeRecording } from '~/session-replay/recording-rasterizer/capture/recorder'
import { config } from '~/session-replay/recording-rasterizer/config'
import { asRasterizationError } from '~/session-replay/recording-rasterizer/errors'
import { createLogger } from '~/session-replay/recording-rasterizer/logger'
import { RasterizationMetrics } from '~/session-replay/recording-rasterizer/metrics'
import { computeVideoTimestamps } from '~/session-replay/recording-rasterizer/postprocess'
import { uploadToS3 } from '~/session-replay/recording-rasterizer/storage'
import {
    ActivityTimings,
    RasterizationProgress,
    RasterizeRecordingInput,
    RasterizeRecordingOutput,
} from '~/session-replay/recording-rasterizer/types'
import { elapsed } from '~/session-replay/recording-rasterizer/utils'

function toActivityError(err: unknown): Error {
    const rasterizationError = asRasterizationError(err)
    if (rasterizationError) {
        // The code travels as the failure type either way, so a caller can tell a recording that can never render
        // (NO_SNAPSHOTS) from one that merely ran out of retries. Retryability stays the player's call: NO_SNAPSHOTS is
        // retryable while a recording is still being ingested, so the code is only conclusive once Temporal has spent
        // the attempts.
        return rasterizationError.retryable
            ? ApplicationFailure.retryable(rasterizationError.message, rasterizationError.code, rasterizationError)
            : ApplicationFailure.nonRetryable(rasterizationError.message, rasterizationError.code, rasterizationError)
    }
    return err instanceof Error ? err : new Error(String(err))
}

async function rasterizeRecordingActivity(
    pool: BrowserPool,
    playerHtml: string,
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

    RasterizationMetrics.activityStarted()
    const activityStart = process.hrtime()
    const id = randomUUID()
    const workDir = process.env.VIDEO_WORK_DIR || os.tmpdir()
    const ext = input.output_format || 'mp4'
    const outputPath = path.join(workDir, `ph-video-${id}.${ext}`)

    const timings: ActivityTimings = { total_s: 0, setup_s: 0, capture_s: 0, upload_s: 0 }

    // Mutated in place by recorder.ts and capture.ts so each heartbeat carries
    // the latest phase and frame count. Temporal exposes this via
    // `pending_activities[].heartbeat_details` for the parent workflow to read.
    const progress: RasterizationProgress = { phase: 'setup', frame: 0, estimatedTotalFrames: 0 }
    let lastProgressAt = Date.now()
    // Stage timings are tracked here rather than trusted from the recorder so they exist on the
    // error path too: knowing how long failing renders run, and in which stage, is the main
    // question the metrics need to answer.
    let phaseStartedAt = Date.now()
    let lastPhase: RasterizationProgress['phase'] = progress.phase
    // Heartbeats fire from puppeteer emitter callbacks and a timer; once the activity context is
    // gone (worker shutdown, cancellation) an uncaught throw would kill the process.
    const safeHeartbeat = (): void => {
        try {
            Context.current().heartbeat(progress)
        } catch {
            // Context gone; nothing to report to.
        }
    }
    const onProgress = (): void => {
        lastProgressAt = Date.now()
        if (progress.phase !== lastPhase) {
            lastPhase = progress.phase
            phaseStartedAt = Date.now()
        }
        safeHeartbeat()
    }

    // Cancellation (workflow cancel, heartbeat-timeout detection) aborts the render by closing the
    // page; without this, the render runs to completion holding a browser and a concurrency slot
    // the server has already given up on.
    const abort = new AbortController()
    const ctx = Context.current()
    const onCancel = (): void => abort.abort()
    ctx.cancellationSignal.addEventListener('abort', onCancel, { once: true })
    if (ctx.cancellationSignal.aborted) {
        abort.abort()
    }

    // Progress-driven heartbeats stop while a beginFrame stalls, so beat on wall clock too, but
    // only up to the stall tolerance, so a hang anywhere else still trips the 30s heartbeat timeout.
    const keepaliveCutoffMs = config.beginFrameTimeoutMs + 30_000
    // Past the cutoff the server has necessarily timed this attempt out (heartbeats stopped), and
    // cancellation can no longer be delivered over heartbeat responses, so a local watchdog is the
    // only thing left that can reclaim the slot from a wedged render.
    const watchdogCutoffMs = keepaliveCutoffMs + 60_000
    const heartbeatInterval = setInterval(() => {
        const sinceProgress = Date.now() - lastProgressAt
        if (sinceProgress > watchdogCutoffMs && !abort.signal.aborted) {
            log.error({ since_progress_s: Math.round(sinceProgress / 1000) }, 'no progress past watchdog, aborting')
            abort.abort()
            return
        }
        if (sinceProgress > keepaliveCutoffMs) {
            return
        }
        try {
            Context.current().heartbeat(progress)
        } catch {
            // The activity context is gone (worker shutdown); an uncaught throw here kills the process.
        }
    }, 10_000)

    try {
        const result = await rasterizeRecording(pool, input, outputPath, playerHtml, onProgress, {
            progress,
            log,
            signal: abort.signal,
        })
        timings.setup_s = result.timings.setup_s
        timings.capture_s = result.timings.capture_s
        RasterizationMetrics.observeSetup('success', timings.setup_s)
        RasterizationMetrics.observeCapture('success', timings.capture_s)

        const periods = computeVideoTimestamps(result.inactivity_periods)

        progress.phase = 'upload'
        onProgress()
        const uploadStart = process.hrtime()
        const format = input.output_format || 'mp4'
        const s3Uri = await uploadToS3(outputPath, input.s3_bucket, input.s3_key_prefix, id, format, onProgress)
        timings.upload_s = elapsed(uploadStart)
        RasterizationMetrics.observeUpload('success', timings.upload_s)

        const stat = await fs.stat(outputPath)
        timings.total_s = elapsed(activityStart)
        RasterizationMetrics.observeActivity('success', timings.total_s)
        RasterizationMetrics.observeVideo(result.capture_duration_s, stat.size, result.frame_count)

        // Total recording duration = active playback time + skipped inactivity. The output video is
        // real-time (the setpts filter undoes the capture speed-up), so capture_duration_s already
        // is active session seconds; multiplying by playback_speed would overstate it.
        const activeSessionS = result.capture_duration_s
        const skippedS = result.inactivity_periods
            .filter((p) => !p.active && p.ts_to_s != null)
            .reduce((sum, p) => sum + (p.ts_to_s! - p.ts_from_s), 0)
        RasterizationMetrics.observeRecordingDuration(activeSessionS + skippedS)

        const output: RasterizeRecordingOutput = {
            s3_uri: s3Uri,
            video_duration_s: result.capture_duration_s,
            playback_speed: result.playback_speed,
            show_metadata_footer: !!input.show_metadata_footer,
            truncated: result.truncated,
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
        // Record how long the failed stage ran; without this the setup/capture/upload series only
        // exist for successes and cannot answer where failing renders spend their time.
        const failedStageS = (Date.now() - phaseStartedAt) / 1000
        if (lastPhase === 'setup') {
            RasterizationMetrics.observeSetup('error', failedStageS)
        } else if (lastPhase === 'capture') {
            RasterizationMetrics.observeCapture('error', failedStageS)
        } else {
            RasterizationMetrics.observeUpload('error', failedStageS)
        }
        const rasterizationError = asRasterizationError(err)
        if (rasterizationError) {
            RasterizationMetrics.incrementError(rasterizationError.code, rasterizationError.retryable)
        } else {
            RasterizationMetrics.incrementError('UNKNOWN', true)
        }
        // Classification collapses the raw rejection into a stable ApplicationFailure message that
        // drops the CDP method and stack. Log the original here, the last point that still holds it,
        // so a setup-phase death (browser-pool logs nothing at error level) stays diagnosable.
        // Non-retryable codes are the recording's own fault (NO_SNAPSHOTS, INVALID_INPUT) and are
        // routine, so they stay off the error level that infra alerts on.
        const logAtErrorLevel = !rasterizationError || rasterizationError.retryable
        const logFailure = logAtErrorLevel ? log.error.bind(log) : log.warn.bind(log)
        logFailure({ err, code: rasterizationError?.code ?? 'UNKNOWN' }, 'rasterization failed')
        throw toActivityError(rasterizationError ?? err)
    } finally {
        clearInterval(heartbeatInterval)
        ctx.cancellationSignal.removeEventListener('abort', onCancel)
        RasterizationMetrics.activityFinished()
        await fs.rm(outputPath, { force: true })
    }
}

export function createActivities(pool: BrowserPool, playerHtml: string) {
    return {
        'rasterize-recording': (input: RasterizeRecordingInput) => rasterizeRecordingActivity(pool, playerHtml, input),
    }
}
