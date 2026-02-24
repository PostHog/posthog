import { Histogram } from 'prom-client'

export class RecordingApiMetrics {
    private static readonly getBlockDuration = new Histogram({
        name: 'recording_api_get_block_duration_seconds',
        help: 'Time taken to serve a getBlock request (S3 fetch + decrypt)',
        labelNames: ['result', 'session_state'],
        buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
    })

    private static readonly deleteRecordingsDuration = new Histogram({
        name: 'recording_api_delete_recordings_duration_seconds',
        help: 'Time taken to delete recordings',
        labelNames: ['result'],
        buckets: [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
    })

    public static observeGetBlock(result: string, seconds: number, sessionState: string): void {
        this.getBlockDuration.labels({ result, session_state: sessionState }).observe(seconds)
    }

    public static observeDeleteRecordings(result: string, seconds: number): void {
        this.deleteRecordingsDuration.labels({ result }).observe(seconds)
    }
}
