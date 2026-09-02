import { Counter, Gauge, Histogram, Summary } from 'prom-client'

import { recordMessagesDroppedByRestrictions } from './otel-metrics'

const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity]

/** Whether the sender device clock reads ahead of or behind the server-stamped message time. */
export type ClockSkewDirection = 'device_ahead' | 'device_behind'

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

    private static readonly messagesByEncoding = new Counter({
        name: 'recording_blob_ingestion_v2_messages_by_encoding',
        help: 'The number of messages received from Kafka broken down by envelope content-encoding',
        labelNames: ['content_encoding'],
    })

    private static readonly messageClockSkew = new Histogram({
        name: 'recording_blob_ingestion_v2_message_clock_skew_seconds',
        help: 'Absolute offset between the sender device clock at upload (sent_at) and the server clock at receipt (now), by direction. Replay skips the skew correction every other event gets, so a large offset means the recording start_time — the default playlist sort — disagrees with the corrected event time.',
        labelNames: ['direction'],
        buckets: [1, 5, 30, 60, 300, 900, 1800, 3600, 7200, 21600, 43200, 86400],
    })

    private static readonly messageClockSkewUnmeasured = new Counter({
        name: 'recording_blob_ingestion_v2_message_clock_skew_unmeasured',
        help: 'Replay messages whose clock offset could not be measured because capture recorded no usable sent_at/now pair. Counted separately so an absent measurement is not read as zero skew',
    })

    private static readonly unbilledNewSession = new Counter({
        name: 'recording_blob_ingestion_v2_unbilled_new_session',
        help: 'New sessions whose first message failed before the usage step, so a later message for the same session bills nothing while the report still counts the recording',
        labelNames: ['reason'],
    })

    public static incrementMessageReceived(partition: number): void {
        this.messageReceived.labels(partition.toString()).inc()
    }

    public static incrementUnbilledNewSession(reason: string): void {
        this.unbilledNewSession.labels(reason).inc()
    }

    public static observeDroppedByRestrictions(count: number): void {
        this.messagesDroppedByRestrictions.inc(count)
        recordMessagesDroppedByRestrictions(count)
    }

    public static observeOverflowedByRestrictions(count: number): void {
        this.messagesOverflowedByRestrictions.inc(count)
    }

    public static incrementMessagesByEncoding(encoding: string): void {
        this.messagesByEncoding.labels(encoding).inc()
    }

    public static incrementMessageClockSkewUnmeasured(): void {
        this.messageClockSkewUnmeasured.inc()
    }

    public static observeMessageClockSkew(direction: ClockSkewDirection, seconds: number): void {
        this.messageClockSkew.labels(direction).observe(seconds)
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
