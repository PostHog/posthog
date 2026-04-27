import { Counter, Gauge, Summary } from 'prom-client'

const QUANTILES = [0.5, 0.95, 0.99]
const MAX_AGE_SECONDS = 600
const AGE_BUCKETS = 5

export class RasterizationMetrics {
    // --- Activity timing ---

    private static readonly activityDuration = new Summary({
        name: 'recording_rasterizer_activity_duration_seconds',
        help: 'Total time for the rasterization activity',
        labelNames: ['result'],
        percentiles: QUANTILES,
        maxAgeSeconds: MAX_AGE_SECONDS,
        ageBuckets: AGE_BUCKETS,
    })

    private static readonly setupDuration = new Summary({
        name: 'recording_rasterizer_setup_duration_seconds',
        help: 'Time spent on browser setup, player load, and recording data fetch',
        labelNames: ['result'],
        percentiles: QUANTILES,
        maxAgeSeconds: MAX_AGE_SECONDS,
        ageBuckets: AGE_BUCKETS,
    })

    private static readonly captureDuration = new Summary({
        name: 'recording_rasterizer_capture_duration_seconds',
        help: 'Time spent on screen capture of the recording playback',
        labelNames: ['result'],
        percentiles: QUANTILES,
        maxAgeSeconds: MAX_AGE_SECONDS,
        ageBuckets: AGE_BUCKETS,
    })

    private static readonly uploadDuration = new Summary({
        name: 'recording_rasterizer_upload_duration_seconds',
        help: 'Time spent uploading the video to S3',
        labelNames: ['result'],
        percentiles: QUANTILES,
        maxAgeSeconds: MAX_AGE_SECONDS,
        ageBuckets: AGE_BUCKETS,
    })

    private static readonly activitiesTotal = new Counter({
        name: 'recording_rasterizer_activities_total',
        help: 'Number of rasterization activities completed',
        labelNames: ['result'],
    })

    // --- Video output ---

    private static readonly videoDuration = new Summary({
        name: 'recording_rasterizer_video_duration_seconds',
        help: 'Duration of the output video',
        percentiles: QUANTILES,
        maxAgeSeconds: MAX_AGE_SECONDS,
        ageBuckets: AGE_BUCKETS,
    })

    private static readonly videoFileSize = new Summary({
        name: 'recording_rasterizer_video_file_size_bytes',
        help: 'Size of the output video file',
        percentiles: QUANTILES,
        maxAgeSeconds: MAX_AGE_SECONDS,
        ageBuckets: AGE_BUCKETS,
    })

    private static readonly videoFramesTotal = new Counter({
        name: 'recording_rasterizer_video_frames_total',
        help: 'Total number of frames captured across all activities',
    })

    private static readonly recordingDuration = new Summary({
        name: 'recording_rasterizer_recording_duration_seconds',
        help: 'Total real-world duration of the recording including inactive periods',
        percentiles: QUANTILES,
        maxAgeSeconds: MAX_AGE_SECONDS,
        ageBuckets: AGE_BUCKETS,
    })

    // --- Errors ---

    private static readonly errorsTotal = new Counter({
        name: 'recording_rasterizer_errors_total',
        help: 'Number of rasterization errors',
        labelNames: ['code', 'retryable'],
    })

    // --- Browser pool ---

    private static readonly browserActive = new Gauge({
        name: 'recording_rasterizer_browser_active',
        help: 'Number of browser instances currently in use',
    })

    private static readonly browserIdle = new Gauge({
        name: 'recording_rasterizer_browser_idle',
        help: 'Number of idle browser instances in the pool',
    })

    private static readonly browserLaunchesTotal = new Counter({
        name: 'recording_rasterizer_browser_launches_total',
        help: 'Total number of browser instances launched',
    })

    private static readonly browserRecyclesTotal = new Counter({
        name: 'recording_rasterizer_browser_recycles_total',
        help: 'Total number of browser instances recycled due to usage limit',
    })

    // --- Concurrency ---

    private static readonly concurrentActivities = new Gauge({
        name: 'recording_rasterizer_concurrent_activities',
        help: 'Number of rasterization activities currently in flight',
    })

    // --- Observe methods ---

    public static observeActivity(result: 'success' | 'error', seconds: number): void {
        this.activityDuration.labels({ result }).observe(seconds)
        this.activitiesTotal.labels({ result }).inc()
    }

    public static observeSetup(result: 'success' | 'error', seconds: number): void {
        this.setupDuration.labels({ result }).observe(seconds)
    }

    public static observeCapture(result: 'success' | 'error', seconds: number): void {
        this.captureDuration.labels({ result }).observe(seconds)
    }

    public static observeUpload(result: 'success' | 'error', seconds: number): void {
        this.uploadDuration.labels({ result }).observe(seconds)
    }

    public static observeVideo(durationS: number, fileSizeBytes: number, frameCount: number): void {
        this.videoDuration.observe(durationS)
        this.videoFileSize.observe(fileSizeBytes)
        this.videoFramesTotal.inc(frameCount)
    }

    public static observeRecordingDuration(seconds: number): void {
        this.recordingDuration.observe(seconds)
    }

    public static incrementError(code: string, retryable: boolean): void {
        this.errorsTotal.labels({ code, retryable: String(retryable) }).inc()
    }

    public static browserLaunched(): void {
        this.browserLaunchesTotal.inc()
    }

    public static browserRecycled(): void {
        this.browserRecyclesTotal.inc()
    }

    public static setBrowserCounts(active: number, idle: number): void {
        this.browserActive.set(active)
        this.browserIdle.set(idle)
    }

    public static activityStarted(): void {
        this.concurrentActivities.inc()
    }

    public static activityFinished(): void {
        this.concurrentActivities.dec()
    }
}
