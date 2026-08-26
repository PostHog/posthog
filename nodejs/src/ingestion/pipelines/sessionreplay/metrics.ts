import { Counter, Gauge, Histogram, Summary } from 'prom-client'

import { recordMessagesDroppedByRestrictions } from './otel-metrics'

const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity]

/** Which anonymizer produced the output; the label makes the flag rollout a direct A/B. */
export type MlAnonymizeImpl = 'rust' | 'ts'
/** Rust engine that produced the output (tree = the parse fallback fired). `''` when not applicable. */
export type MlAnonymizeRoute = 'stream' | 'tree' | ''

export type MlImageLaneStage = 'collected' | 'deduped' | 'queued' | 'produced' | 'produce_failed'

/** Stages of the URL lane. Deliberately the same vocabulary as {@link MlImageLaneStage}, so the two
 *  lanes read the same way on a dashboard even though only `collected` exists until the fetch lane
 *  ships. */
export type MlUrlLaneStage = 'collected' | 'deduped' | 'queued' | 'produced' | 'produce_failed' | 'ref_unusable'
export type MlUrlCrawlHistoryOutcome = 'fresh' | 'miss' | 'error'

const URL_BYTES_SAMPLE_RATE = 16

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

    private static readonly mlAnonymizeDuration = new Histogram({
        name: 'recording_blob_ingestion_v2_ml_anonymize_duration_ms',
        help: 'Per-message ML mirror anonymize time in ms, by implementation and route',
        labelNames: ['impl', 'route'],
        // The measured interval includes libuv threadpool queue wait, which under backpressure
        // reaches tens of seconds — the tail buckets exist so quantiles don't clamp at 10s.
        buckets: [0, 1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000, Infinity],
    })

    private static readonly mlAnonymizeFailed = new Counter({
        name: 'recording_blob_ingestion_v2_ml_anonymize_failed',
        help: 'Messages dropped because ML mirror anonymization failed (fail-closed), by implementation',
        labelNames: ['impl'],
    })

    private static readonly mlImagesCollected = new Counter({
        name: 'recording_blob_ingestion_v2_ml_images_collected',
        help: 'Images through the out-of-band scrub lane, by stage: collected (returned by the addon), deduped (suppressed by the cross-message cache), queued (handed to the producer), produced (delivery acked), produce_failed (delivery failed; refs un-marked for natural retry)',
        labelNames: ['outcome'],
    })

    private static readonly mlUrlsCollected = new Counter({
        name: 'recording_blob_ingestion_v2_ml_urls_collected',
        help: 'Remote image URLs through the fetch lane, by stage: collected (returned by the addon), deduped (suppressed by the cross-message cache), queued (handed to the producer), produced (delivery acked), produce_failed (delivery failed)',
        labelNames: ['outcome'],
    })

    private static readonly mlUrlCrawlHistory = new Counter({
        name: 'recording_blob_ingestion_v2_ml_url_crawl_history_total',
        help: 'URL jobs checked by the mirror before Kafka: fresh jobs are suppressed, misses are produced, and errors fail open',
        labelNames: ['outcome'],
    })

    private static readonly mlUrlCrawlHistoryDuration = new Histogram({
        name: 'recording_blob_ingestion_v2_ml_url_crawl_history_duration_seconds',
        help: 'Wall time for one mirror crawl-history read by outcome',
        labelNames: ['outcome'],
        buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
    })

    private static readonly mlUrlsDeclined = new Counter({
        name: 'recording_blob_ingestion_v2_ml_urls_declined',
        help: 'Remote image URLs the anonymizer refused to collect, by reason. A decline is invisible in the collected count, so without this the lane looks like traffic carries fewer images than it does',
        labelNames: ['reason'],
    })

    private static readonly mlUrlDomainsPerMessage = new Histogram({
        name: 'recording_blob_ingestion_v2_ml_url_domains_per_message',
        help: 'Distinct registrable domains among the URLs collected from one message, observed for every message including those with none. The fetch topic is keyed by that domain, so this is how many Kafka messages one replay message becomes, and how concentrated a page is on one operator',
        buckets: [0, 1, 2, 3, 5, 8, 13, 21, 34, 55],
    })

    private static readonly mlUrlsPerMessage = new Histogram({
        name: 'recording_blob_ingestion_v2_ml_urls_per_message',
        help: 'URLs collected from one message that carried at least one. The counter alone gives a mean; sizing the fetch lane needs the tail',
        buckets: [1, 2, 5, 10, 25, 50, 100, 256, 512],
    })

    private static readonly mlImageBytesProduced = new Counter({
        name: 'recording_blob_ingestion_v2_ml_image_bytes_produced',
        help: 'Bytes of collected images delivered to the scrub topic (acked)',
    })

    private static readonly mlImagePseudoTeamInvalid = new Counter({
        name: 'recording_blob_ingestion_v2_ml_image_pseudo_team_invalid',
        help: 'Messages whose derived team pseudonym failed the consumer ref-shape check; collection disabled for them (inline blur instead)',
    })

    public static incrementMessageReceived(partition: number): void {
        this.messageReceived.labels(partition.toString()).inc()
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

    public static observeMlAnonymizeDuration(impl: MlAnonymizeImpl, ms: number, route: MlAnonymizeRoute = ''): void {
        this.mlAnonymizeDuration.labels(impl, route).observe(ms)
    }

    public static incrementMlAnonymizeFailed(impl: MlAnonymizeImpl): void {
        this.mlAnonymizeFailed.labels(impl).inc()
    }

    public static incrementMlImagesCollected(outcome: MlImageLaneStage, count: number): void {
        this.mlImagesCollected.labels(outcome).inc(count)
    }

    private static readonly mlUrlBytes = new Histogram({
        name: 'recording_blob_ingestion_v2_ml_url_bytes',
        help: 'Bytes in one collected remote image URL, sampled. The tail sizes the per-record packing budget, because a record is filled by bytes rather than by a fixed number of URLs. Read the shape, not the count: one URL in URL_BYTES_SAMPLE_RATE is observed',
        buckets: [64, 128, 256, 512, 1024, 2048],
    })
    /**
     * A message can carry hundreds of URLs, and an observation costs several allocations, so
     * observing each one puts the size of the payload on the mirror's hot path.
     */
    private static urlBytesSeen = 0
    private static readonly mlUrlsPerRecord = new Histogram({
        name: 'recording_blob_ingestion_v2_ml_urls_per_record',
        help: 'URLs packed into one record on the fetch topic. Bounded in practice by the collector cap per message, since a record holds one domain from one message',
        buckets: [1, 8, 32, 64, 128, 256, 512],
    })
    private static readonly mlUrlRecordBytes = new Histogram({
        name: 'recording_blob_ingestion_v2_ml_url_record_bytes',
        help: 'Serialized bytes of one record on the fetch topic. Read against librdkafka message.max.bytes, which this producer leaves at its 1,000,000 byte default: the packing budget is what keeps a record under it',
        buckets: [1024, 8192, 65536, 262144, 524288, 1_000_000],
    })

    public static observeMlUrlBytes(bytes: number): void {
        if (this.urlBytesSeen++ % URL_BYTES_SAMPLE_RATE === 0) {
            this.mlUrlBytes.observe(bytes)
        }
    }
    public static observeMlUrlRecord(urls: number, bytes: number): void {
        this.mlUrlsPerRecord.observe(urls)
        this.mlUrlRecordBytes.observe(bytes)
    }
    public static incrementMlUrlsCollected(outcome: MlUrlLaneStage, count: number): void {
        this.mlUrlsCollected.labels(outcome).inc(count)
    }

    public static incrementMlUrlCrawlHistory(outcome: MlUrlCrawlHistoryOutcome, count: number): void {
        this.mlUrlCrawlHistory.labels(outcome).inc(count)
    }

    public static observeMlUrlCrawlHistoryDuration(outcome: 'success' | 'error', durationSeconds: number): void {
        this.mlUrlCrawlHistoryDuration.labels(outcome).observe(durationSeconds)
    }

    public static incrementMlUrlsDeclined(reason: string, count: number): void {
        if (count > 0) {
            this.mlUrlsDeclined.inc({ reason }, count)
        }
    }

    public static observeMlUrlDomainsPerMessage(domains: number): void {
        this.mlUrlDomainsPerMessage.observe(domains)
    }

    public static observeMlUrlsPerMessage(urls: number): void {
        this.mlUrlsPerMessage.observe(urls)
    }

    public static incrementMlImageBytesProduced(bytes: number): void {
        this.mlImageBytesProduced.inc(bytes)
    }

    public static incrementMlImagePseudoTeamInvalid(): void {
        this.mlImagePseudoTeamInvalid.inc()
    }
}
