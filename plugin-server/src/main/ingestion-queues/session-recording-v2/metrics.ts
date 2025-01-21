import { Counter, Gauge, Histogram, Summary } from 'prom-client'

const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity]

export class SessionRecordingMetrics {
    private static instance: SessionRecordingMetrics

    private readonly sessionsHandled: Gauge<string>
    private readonly sessionsRevoked: Gauge<string>
    private readonly kafkaBatchSize: Histogram<string>
    private readonly kafkaBatchSizeKb: Histogram<string>
    private readonly sessionInfo: Summary<string>
    private readonly messageReceived: Counter<string>

    private constructor() {
        this.sessionsHandled = new Gauge({
            name: 'recording_blob_ingestion_v2_session_manager_count',
            help: 'A gauge of the number of sessions being handled by this blob ingestion consumer',
        })

        this.sessionsRevoked = new Gauge({
            name: 'recording_blob_ingestion_v2_sessions_revoked',
            help: 'A gauge of the number of sessions being revoked when partitions are revoked when a re-balance occurs',
        })

        this.kafkaBatchSize = new Histogram({
            name: 'recording_blob_ingestion_v2_kafka_batch_size',
            help: 'The size of the batches we are receiving from Kafka',
            buckets: [
                0,
                1,
                5,
                10,
                25,
                50,
                100,
                150,
                200,
                250,
                300,
                350,
                400,
                500,
                750,
                1000,
                1500,
                2000,
                3000,
                Infinity,
            ],
        })

        this.kafkaBatchSizeKb = new Histogram({
            name: 'recording_blob_ingestion_v2_kafka_batch_size_kb',
            help: 'The size in kb of the batches we are receiving from Kafka',
            buckets: BUCKETS_KB_WRITTEN,
        })

        this.sessionInfo = new Summary({
            name: 'recording_blob_ingestion_v2_session_info_bytes',
            help: 'Size of aggregated session information being processed',
            percentiles: [0.1, 0.25, 0.5, 0.9, 0.99],
        })

        this.messageReceived = new Counter({
            name: 'recording_blob_ingestion_v2_kafka_message_received',
            help: 'The number of messages we have received from Kafka',
            labelNames: ['partition'],
        })
    }

    public static getInstance(): SessionRecordingMetrics {
        if (!SessionRecordingMetrics.instance) {
            SessionRecordingMetrics.instance = new SessionRecordingMetrics()
        }
        return SessionRecordingMetrics.instance
    }

    public resetSessionsRevoked(): void {
        this.sessionsRevoked.reset()
    }

    public resetSessionsHandled(): void {
        this.sessionsHandled.reset()
    }

    public observeKafkaBatchSize(size: number): void {
        this.kafkaBatchSize.observe(size)
    }

    public observeKafkaBatchSizeKb(sizeKb: number): void {
        this.kafkaBatchSizeKb.observe(sizeKb)
    }

    public observeSessionInfo(bytes: number): void {
        this.sessionInfo.observe(bytes)
    }

    public incrementMessageReceived(partition: number): void {
        this.messageReceived.inc({ partition })
    }
}
