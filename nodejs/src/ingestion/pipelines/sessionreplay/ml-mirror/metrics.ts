import { Counter, Histogram } from 'prom-client'

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
export type MlImageSource = 'css' | 'html'
export type MlImageSourceKind = 'inline' | 'url'

const URL_BYTES_SAMPLE_RATE = 16

export class MlMirrorMetrics {
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

    private static readonly mlImageReferencesByProperty = new Counter({
        name: 'recording_blob_ingestion_v2_ml_image_references_by_property',
        help: 'Collected CSS and HTML image ref occurrences by bounded source, property, and lane. Counts references before per-message content or URL deduplication',
        labelNames: ['source', 'property', 'kind'],
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

    public static observeMlAnonymizeDuration(impl: MlAnonymizeImpl, ms: number, route: MlAnonymizeRoute = ''): void {
        this.mlAnonymizeDuration.labels(impl, route).observe(ms)
    }

    public static incrementMlAnonymizeFailed(impl: MlAnonymizeImpl): void {
        this.mlAnonymizeFailed.labels(impl).inc()
    }

    public static incrementMlImagesCollected(outcome: MlImageLaneStage, count: number): void {
        this.mlImagesCollected.labels(outcome).inc(count)
    }

    public static incrementMlImageReferencesByProperty(
        source: MlImageSource,
        property: string,
        kind: MlImageSourceKind,
        count: number
    ): void {
        if (count > 0) {
            this.mlImageReferencesByProperty.labels(source, property, kind).inc(count)
        }
    }

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

// Days. A batch that spans dates files the whole object under its oldest event date (see objectKey), so
// these buckets are chosen to separate a same-day batch (span 0) from one dragged back by a straggler.
const PARTITION_DAY_BUCKETS = [0, 1, 2, 3, 7, 14, 30, 90, 365]

/**
 * Metrics for the ML block-metadata Parquet sink (drains the mirror's block-metadata topic to the ML
 * bucket). The sink can consume and commit offsets while writing nothing: if every row is rejected the
 * buffer stays empty, so flush advances offsets without a write. Kafka lag alone can't see that state.
 */
export class MlParquetSinkMetrics {
    private static readonly rowsParsed = new Counter({
        name: 'ml_mirror_parquet_sink_rows_parsed_total',
        help: 'Block-metadata rows parsed from Kafka and accepted into the Parquet buffer',
    })
    private static readonly rowsRejected = new Counter({
        name: 'ml_mirror_parquet_sink_rows_rejected_total',
        help: 'Block-metadata Kafka messages skipped before buffering, by reason',
        labelNames: ['reason'],
    })
    private static readonly objectsWritten = new Counter({
        name: 'ml_mirror_parquet_sink_objects_written_total',
        help: 'Parquet objects written to the ML bucket',
    })
    private static readonly rowsWritten = new Counter({
        name: 'ml_mirror_parquet_sink_rows_written_total',
        help: 'Block-metadata rows written to the ML bucket as Parquet',
    })
    private static readonly bytesWritten = new Counter({
        name: 'ml_mirror_parquet_sink_bytes_written_total',
        help: 'Parquet bytes written to the ML bucket',
    })
    private static readonly writeErrors = new Counter({
        name: 'ml_mirror_parquet_sink_write_errors_total',
        help: 'Parquet object writes that threw (the batch replays from Kafka)',
    })
    private static readonly flushes = new Counter({
        name: 'ml_mirror_parquet_sink_flushes_total',
        help: 'Batcher flushes by outcome: wrote a Parquet object, or committed offsets with an empty buffer',
        labelNames: ['outcome'],
    })
    private static readonly partitionLagDays = new Histogram({
        name: 'ml_mirror_parquet_sink_partition_lag_days',
        help: "Days between an object's partition date (its oldest event date) and write time",
        buckets: PARTITION_DAY_BUCKETS,
    })
    private static readonly eventDateSpanDays = new Histogram({
        name: 'ml_mirror_parquet_sink_event_date_span_days',
        help: 'Days between the oldest and newest event date in one written object; a non-zero span means a mixed-date batch whose partition date understates most of its rows',
        buckets: PARTITION_DAY_BUCKETS,
    })

    public static incRowsParsed(count: number): void {
        this.rowsParsed.inc(count)
    }
    public static incRowsRejected(reason: 'parse_failed' | 'invalid'): void {
        this.rowsRejected.labels(reason).inc()
    }
    public static observeWrite(rows: number, bytes: number): void {
        this.objectsWritten.inc()
        this.rowsWritten.inc(rows)
        this.bytesWritten.inc(bytes)
    }
    public static incWriteError(): void {
        this.writeErrors.inc()
    }
    public static incFlush(outcome: 'written' | 'empty'): void {
        this.flushes.labels(outcome).inc()
    }
    public static observePartition(lagDays: number, spanDays: number): void {
        this.partitionLagDays.observe(lagDays)
        this.eventDateSpanDays.observe(spanDays)
    }
}
