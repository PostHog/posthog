import { Counter, Gauge, Histogram } from 'prom-client'

import { ScrubWaitReason } from './scrub-client'

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
     * and unlike the seen-ref cache the fix is poll configuration rather than memory. Buckets stop at
     * the CONSUMER_BATCH_SIZE fetch cap, past which they could never be populated. This deliberately
     * excludes empty polls, which is what makes it readable where consumer-v1's own batch-size
     * histogram is not: that one samples before the empty check, and this lane runs with
     * callEachBatchWhenEmpty, so idle polls bury the real distribution in the lowest bucket.
     */
    private static readonly batchMessages = new Histogram({
        name: 'ml_mirror_image_scrub_consumer_batch_messages',
        help: 'Messages per non-empty poll batch. Read alongside deduped{scope="batch"}: consistently small batches cap how much intra-batch dedup can collapse, whatever the duplicate rate is',
        buckets: [1, 10, 50, 100, 200, 300, 400, 500],
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
    /**
     * The saturation signal, and the one to alert on.
     *
     * Each increment is one attempt that came back without bytes and will be retried rather than
     * abandoned, so this never means data was lost. What it means is that the consumer is spending
     * wall time waiting on the sidecar instead of draining, which is the thing that turns into lag.
     * Read it against `scrubbed`: a small ratio is a lane near its ceiling, and a large one means the
     * sidecar is not keeping up and the backlog is growing.
     */
    private static readonly scrubWaits = new Counter({
        name: 'ml_mirror_image_scrub_consumer_scrub_waits_total',
        help: 'Scrub attempts that returned no bytes and will be retried, by reason: "busy" (503, shed), "timeout" (no reply inside the request timeout), "transport" (socket refused or reset, or an unexpected status). Retried rather than dropped, so this is backpressure and not loss',
        labelNames: ['reason'],
    })
    /**
     * Images that have been retried long past what any healthy sidecar needs for one image.
     *
     * Separate from the wait counter because it means something different. Waits rise and fall with
     * load; this rising while `scrub_waits_total{reason="busy"}` is flat points at one image the
     * sidecar cannot process rather than at capacity, and that image is holding the head of its
     * partition. The log line beside it carries the ref.
     */
    private static readonly stuckImages = new Counter({
        name: 'ml_mirror_image_scrub_consumer_stuck_images_total',
        help: 'Images still being retried after the point where a healthy sidecar would have finished, so likely unprocessable rather than merely queued. Each one holds the head of its partition until it succeeds',
    })
    /**
     * How much of a batch reached a recordable offset, and how long the batch took.
     *
     * Offsets retire contiguously from the front, so one image stuck at the head holds back every
     * completed image behind it: the pod carries their bytes without being able to commit any of
     * them. Nothing else distinguishes that from a batch that was simply slow, and the difference
     * matters, because a batch running long against max.poll.interval.ms is what gets the pod
     * evicted and its work redone elsewhere.
     */
    private static readonly batchRetiredRatio = new Histogram({
        name: 'ml_mirror_image_scrub_consumer_batch_retired_ratio',
        help: 'Share of a batch that retired to a recordable offset. Well under 1 means head-of-line blocking: later images finished but a stuck one at the front prevented any offset advancing',
        buckets: [0, 0.25, 0.5, 0.75, 0.9, 0.99, 1],
    })
    private static readonly batchDuration = new Histogram({
        name: 'ml_mirror_image_scrub_consumer_batch_duration_seconds',
        help: 'Wall time per poll batch. Read against Kafka max.poll.interval.ms (300s): batches approaching it get the pod evicted mid-batch, and the partition is redone by whoever picks it up',
        buckets: [1, 5, 15, 30, 60, 120, 240, 300, 600],
    })
    private static activeBatchStartedAtMs: number | undefined
    private static readonly activeBatchElapsed = new Gauge({
        name: 'ml_mirror_image_scrub_consumer_active_batch_elapsed_seconds',
        help: 'Elapsed wall time of the active non-empty poll batch, or zero between batches. This exposes a stuck batch before Kafka max.poll.interval.ms revokes it',
        collect() {
            const startedAtMs = ImageScrubConsumerMetrics.activeBatchStartedAtMs
            this.set(startedAtMs === undefined ? 0 : Math.max(0, performance.now() - startedAtMs) / 1000)
        },
    })
    /**
     * Images parked on the dead-letter topic because the sidecar could not process them.
     *
     * Not a loss counter: the bytes are still in Kafka, and the reason this exists at all is that
     * one such image otherwise holds the head of its partition against every team whose records
     * share it. It should sit at zero. Anything above a trickle is a sidecar bug reproducing across
     * many images rather than a genuinely odd one, and the fix is in the sidecar, not here.
     */
    private static readonly deadLettered = new Counter({
        name: 'ml_mirror_image_scrub_consumer_dead_lettered_total',
        help: 'Images published to the dead-letter topic after the sidecar repeatedly failed on them while succeeding on others. The bytes are retained, so this is quarantine rather than loss',
        labelNames: ['reason'],
    })
    /**
     * Failed attempts to park an image, each of which leaves it at the head of its partition.
     *
     * Distinct from the dead-letter counter because the consequence is opposite: this is the lane
     * stalled on an image it cannot scrub and cannot put anywhere, which is the pre-dead-letter
     * behaviour and needs the topic looked at (wrong cluster, missing, or max.message.bytes below
     * what a source image can be).
     */
    private static readonly deadLetterFailed = new Counter({
        name: 'ml_mirror_image_scrub_consumer_dead_letter_failed_total',
        help: 'Attempts to publish to the dead-letter topic that failed. Each leaves an unscrubbed image holding the head of its partition, so a sustained rate means the topic is misconfigured rather than that images are bad',
    })
    /**
     * Parked images pushed back at the source topic by a replay run, and those left behind.
     *
     * `exhausted` is the one that needs reading: those images have been round-tripped as often as
     * they are allowed to be and will not be replayed again, so they stay parked until someone
     * either fixes what rejects them or accepts losing them to retention.
     */
    private static readonly replayed = new Counter({
        name: 'ml_mirror_image_scrub_consumer_replayed_total',
        help: 'Parked images published back to the source topic by a replay run',
    })
    private static readonly replayExhausted = new Counter({
        name: 'ml_mirror_image_scrub_consumer_replay_exhausted_total',
        help: 'Parked images a replay run left in place because they have already been round-tripped the maximum number of times, so the sidecar still cannot process them',
    })
    private static readonly offsetsDiscarded = new Counter({
        name: 'ml_mirror_image_scrub_consumer_offsets_discarded_total',
        help: 'Offsets that could not be stored because a rebalance had already revoked the partition, so that span rescrubs under its new owner',
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
    public static incScrubWait(reason: ScrubWaitReason): void {
        this.scrubWaits.labels(reason).inc()
    }
    public static incStuckImage(): void {
        this.stuckImages.inc()
    }
    public static observeBatchProgress(retired: number, planned: number, durationSeconds: number): void {
        if (planned > 0) {
            this.batchRetiredRatio.observe(retired / planned)
        }
        this.batchDuration.observe(durationSeconds)
    }
    public static startBatch(nowMs = performance.now()): void {
        this.activeBatchStartedAtMs = nowMs
    }
    public static finishBatch(): void {
        this.activeBatchStartedAtMs = undefined
    }
    public static incDeadLettered(reason: ScrubWaitReason): void {
        this.deadLettered.labels(reason).inc()
    }
    public static incDeadLetterFailed(): void {
        this.deadLetterFailed.inc()
    }
    public static incReplayed(): void {
        this.replayed.inc()
    }
    public static incReplayExhausted(): void {
        this.replayExhausted.inc()
    }
    public static incOffsetsDiscarded(count: number): void {
        this.offsetsDiscarded.inc(count)
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
