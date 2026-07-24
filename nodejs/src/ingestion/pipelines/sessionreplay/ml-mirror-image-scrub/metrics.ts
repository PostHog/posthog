import { Counter, Histogram } from 'prom-client'

export class ImageScrubConsumerMetrics {
    private static readonly scrubbed = new Counter({
        name: 'ml_mirror_image_scrub_consumer_scrubbed_total',
        help: 'Images scrubbed by the sidecar and buffered for a shard write',
    })
    private static readonly skipped = new Counter({
        name: 'ml_mirror_image_scrub_consumer_skipped_total',
        help: 'Images skipped because the sidecar rejected them as undecodable (resolve to nothing)',
    })
    private static readonly deduped = new Counter({
        name: 'ml_mirror_image_scrub_consumer_deduped_total',
        help: 'Messages skipped as duplicate produces of a ref, by scope: "batch" (another copy in the same poll batch) or "pod" (this pod scrubbed it earlier). Dedup hit rate = deduped / (deduped + scrubbed + skipped); the batch/pod split says how much the retained seen-ref cache is earning over free intra-batch dedup',
        labelNames: ['scope'],
    })
    /**
     * Intra-batch dedup can only collapse copies that arrive in the same poll batch, so its ceiling is
     * set by how many messages a batch holds. Small batches are the one way it can be "undersized",
     * and unlike the seen-ref cache the fix is poll configuration rather than memory.
     */
    private static readonly batchMessages = new Histogram({
        name: 'ml_mirror_image_scrub_consumer_batch_messages',
        help: 'Messages per poll batch. Read alongside deduped{scope="batch"}: consistently small batches cap how much intra-batch dedup can collapse, whatever the duplicate rate is',
        buckets: [1, 10, 50, 100, 500, 1000, 5000, 10000],
    })
    private static readonly invalidKey = new Counter({
        name: 'ml_mirror_image_scrub_consumer_invalid_key_total',
        help: 'Messages dropped because the key is missing, not an image ref, or the value is empty — a sustained rate means producer/consumer ref-format drift is zeroing the lane',
    })
    private static readonly shardsWritten = new Counter({
        name: 'ml_mirror_image_scrub_consumer_shards_written_total',
        help: 'Shard objects (+ their parquet index) written to S3',
    })
    private static readonly shardImages = new Counter({
        name: 'ml_mirror_image_scrub_consumer_shard_images_total',
        help: 'Images written into shards',
    })
    private static readonly shardBytes = new Counter({
        name: 'ml_mirror_image_scrub_consumer_shard_bytes_total',
        help: 'Scrubbed image bytes written into shards',
    })
    private static readonly batchFailed = new Counter({
        name: 'ml_mirror_image_scrub_consumer_batch_failed_total',
        help: 'Batches that threw and will replay, by cause (scrub or write)',
        labelNames: ['cause'],
    })

    public static incBatchFailed(cause: 'scrub' | 'write'): void {
        this.batchFailed.labels(cause).inc()
    }
    public static incScrubbed(): void {
        this.scrubbed.inc()
    }
    public static incSkipped(): void {
        this.skipped.inc()
    }
    public static incDeduped(scope: 'batch' | 'pod'): void {
        this.deduped.labels(scope).inc()
    }
    public static incInvalidKey(): void {
        this.invalidKey.inc()
    }
    public static observeBatchMessages(count: number): void {
        this.batchMessages.observe(count)
    }
    public static observeShard(images: number, bytes: number): void {
        this.shardsWritten.inc()
        this.shardImages.inc(images)
        this.shardBytes.inc(bytes)
    }
}
