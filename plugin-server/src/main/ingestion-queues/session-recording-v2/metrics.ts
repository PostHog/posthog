import { Counter, Gauge, Histogram, Summary } from 'prom-client'

const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity]

export class SessionRecordingIngesterMetrics {
    private static readonly sessionsHandled = new Gauge({
        name: 'recording_blob_ingestion_v2_session_manager_count',
        help: 'A gauge of the number of sessions being handled by this blob ingestion consumer',
    })

    private static readonly sessionsRevoked = new Gauge({
        name: 'recording_blob_ingestion_v2_sessions_revoked',
        help: 'A gauge of the number of sessions being revoked when partitions are revoked when a re-balance occurs',
    })

    private static readonly kafkaBatchSize = new Histogram({
        name: 'recording_blob_ingestion_v2_kafka_batch_size',
        help: 'The size of the batches we are receiving from Kafka',
        buckets: [0, 1, 5, 10, 25, 50, 100, 150, 200, 250, 300, 350, 400, 500, 750, 1000, 1500, 2000, 3000, Infinity],
    })

    private static readonly kafkaBatchSizeKb = new Histogram({
        name: 'recording_blob_ingestion_v2_kafka_batch_size_kb',
        help: 'The size in kb of the batches we are receiving from Kafka',
        buckets: BUCKETS_KB_WRITTEN,
    })

    private static readonly sessionInfo = new Summary({
        name: 'recording_blob_ingestion_v2_session_info_bytes',
        help: 'Size of aggregated session information being processed',
        percentiles: [0.1, 0.25, 0.5, 0.9, 0.99],
    })

    private static readonly messageReceived = new Counter({
        name: 'recording_blob_ingestion_v2_kafka_message_received',
        help: 'The number of messages we have received from Kafka',
        labelNames: ['partition'],
    })

    private static readonly messagesDroppedByRestrictions = new Counter({
        name: 'recording_blob_ingestion_v2_messages_dropped_by_restrictions',
        help: 'The number of messages dropped due to event ingestion restrictions',
    })

    private static readonly messagesOverflowedByRestrictions = new Counter({
        name: 'recording_blob_ingestion_v2_messages_overflowed_by_restrictions',
        help: 'The number of messages redirected to overflow due to event ingestion restrictions',
    })

    public static incrementMessageReceived(partition: number, count: number = 1): void {
        this.messageReceived.labels(partition.toString()).inc(count)
    }

    public static observeDroppedByRestrictions(count: number): void {
        this.messagesDroppedByRestrictions.inc(count)
    }

    public static observeOverflowedByRestrictions(count: number): void {
        this.messagesOverflowedByRestrictions.inc(count)
    }

    public static resetSessionsRevoked(): void {
        this.sessionsRevoked.set(0)
    }

    public static resetSessionsHandled(): void {
        this.sessionsHandled.set(0)
    }

    public static observeSessionInfo(rawSize: number): void {
        this.sessionInfo.observe(rawSize)
    }

    public static observeKafkaBatchSize(size: number): void {
        this.kafkaBatchSize.observe(size)
    }

    public static observeKafkaBatchSizeKb(sizeKb: number): void {
        this.kafkaBatchSizeKb.observe(sizeKb)
    }
}
