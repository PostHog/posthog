import { Counter, Gauge, Histogram } from 'prom-client'

export class RasterizationMetrics {
    // --- Activity timing ---

    private static readonly activityDuration = new Histogram({
        name: 'recording_rasterizer_activity_duration_seconds',
        help: 'Total time for the rasterization activity',
        labelNames: ['result'],
        buckets: [1, 5, 10, 30, 60, 120, 300, 600],
    })

    private static readonly setupDuration = new Histogram({
        name: 'recording_rasterizer_setup_duration_seconds',
        help: 'Time spent on browser setup, player load, and recording data fetch',
        labelNames: ['result'],
        buckets: [0.5, 1, 2, 5, 10, 20, 30, 60],
    })

    private static readonly captureDuration = new Histogram({
        name: 'recording_rasterizer_capture_duration_seconds',
        help: 'Time spent on screen capture of the recording playback',
        labelNames: ['result'],
        buckets: [1, 5, 10, 30, 60, 120, 300, 600],
    })

    private static readonly uploadDuration = new Histogram({
        name: 'recording_rasterizer_upload_duration_seconds',
        help: 'Time spent uploading the video to S3',
        labelNames: ['result'],
        buckets: [0.1, 0.5, 1, 2, 5, 10, 30, 60],
    })

    private static readonly activitiesTotal = new Counter({
        name: 'recording_rasterizer_activities_total',
        help: 'Number of rasterization activities completed',
        labelNames: ['result'],
    })

    // --- Video output ---

    private static readonly videoDuration = new Histogram({
        name: 'recording_rasterizer_video_duration_seconds',
        help: 'Duration of the output video',
        buckets: [1, 5, 10, 30, 60, 120, 300, 600],
    })

    private static readonly videoFileSize = new Histogram({
        name: 'recording_rasterizer_video_file_size_bytes',
        help: 'Size of the output video file',
        buckets: [1024, 10240, 102400, 512000, 1048576, 5242880, 10485760, 52428800],
    })

    private static readonly videoFramesTotal = new Counter({
        name: 'recording_rasterizer_video_frames_total',
        help: 'Total number of frames captured across all activities',
    })

    private static readonly recordingDuration = new Histogram({
        name: 'recording_rasterizer_recording_duration_seconds',
        help: 'Total real-world duration of the recording including inactive periods',
        buckets: [10, 30, 60, 300, 600, 1800, 3600, 7200],
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
