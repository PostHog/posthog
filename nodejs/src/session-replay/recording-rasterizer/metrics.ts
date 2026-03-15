import { Counter, Histogram } from 'prom-client'

export class RasterizationMetrics {
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
}
