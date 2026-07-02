import { Counter } from 'prom-client'

/** Consumer-side scrub/shard metrics (the sidecar reports its own scrub timing separately). */
export class ImageScrubConsumerMetrics {
    private static readonly scrubbed = new Counter({
        name: 'ml_mirror_image_scrub_consumer_scrubbed_total',
        help: 'Images scrubbed by the sidecar and buffered for a shard write',
    })
    private static readonly skipped = new Counter({
        name: 'ml_mirror_image_scrub_consumer_skipped_total',
        help: 'Images skipped because the sidecar rejected them as undecodable (resolve to nothing)',
    })
    private static readonly mismatch = new Counter({
        name: 'ml_mirror_image_scrub_consumer_key_content_mismatch_total',
        help: 'Messages dropped because the key hash did not match the value bytes (forged/corrupt key)',
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

    public static incScrubbed(): void {
        this.scrubbed.inc()
    }
    public static incSkipped(): void {
        this.skipped.inc()
    }
    public static incMismatch(): void {
        this.mismatch.inc()
    }
    public static observeShard(images: number, bytes: number): void {
        this.shardsWritten.inc()
        this.shardImages.inc(images)
        this.shardBytes.inc(bytes)
    }
}
