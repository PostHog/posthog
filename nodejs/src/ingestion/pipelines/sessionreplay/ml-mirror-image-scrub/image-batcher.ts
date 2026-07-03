/** Accumulates scrubbed images across Kafka batches and flushes one shard + parquet index per flush (spanning
 *  many teams) on a time/size threshold — mirrors BlockMetadataBatcher's store-offsets-only-after-a-successful-write model. */
import { Message, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import { ConcurrencyController } from '~/common/utils/concurrencyController'

import { hashImageBytes, isImageRef, parseImageRef } from './content-ref'
import { ImageShardStore, ScrubbedImage } from './image-shard-store'
import { ImageScrubConsumerMetrics } from './metrics'
import { ScrubClient } from './scrub-client'

/** The subset of the Kafka consumer the batcher needs: storing offsets it has durably written. */
export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

export interface ImageBatcherOptions {
    flushIntervalMs: number
    maxImages: number
    maxBytes: number
    scrubConcurrency: number
    /** Wall-clock cap on scrubbing one Kafka batch. Must stay under the consumer's max.poll.interval.ms: if a
     *  hung sidecar held the poll loop past it, the broker would evict us mid-batch and the window would
     *  livelock. On timeout we abort the in-flight scrubs and throw, so the window replays cleanly instead. */
    batchDeadlineMs: number
}

export class ImageBatcher {
    private buffer: ScrubbedImage[] = []
    private bufferBytes = 0
    private pendingOffsets = new Map<string, TopicPartitionOffset>()
    private lastFlushMs: number
    private readonly scrubConcurrency: ConcurrencyController

    constructor(
        private readonly store: ImageShardStore,
        private readonly offsetStore: OffsetStore,
        private readonly scrubClient: ScrubClient,
        private readonly options: ImageBatcherOptions,
        nowMs: number
    ) {
        this.lastFlushMs = nowMs
        this.scrubConcurrency = new ConcurrencyController(options.scrubConcurrency)
    }

    /** Scrub a batch (bounded concurrency), buffer the results, and flush once old/large enough. Throws if
     *  the sidecar is unavailable, leaving the window uncommitted so it replays (at-least-once). */
    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        for (const image of await this.scrubBatch(messages)) {
            this.buffer.push(image)
            this.bufferBytes += image.bytes.length
        }
        // Track the next offset to read per partition (highest seen + 1) even for all-skipped batches, so
        // those don't replay forever.
        for (const offset of findOffsetsToCommit(messages)) {
            this.pendingOffsets.set(`${offset.topic}:${offset.partition}`, offset)
        }
        if (this.shouldFlush(nowMs)) {
            await this.flush(nowMs)
        }
    }

    /** Scrub every message with bounded concurrency; skips resolve to null, transient sidecar failures
     *  reject out of here (→ the batch replays). A wall-clock deadline aborts the whole batch so a hung
     *  sidecar can't hold the poll loop long enough to get us evicted from the consumer group. */
    private async scrubBatch(messages: Message[]): Promise<ScrubbedImage[]> {
        const controller = new AbortController()
        const timer = setTimeout(() => controller.abort(), this.options.batchDeadlineMs)
        try {
            const scrubbed = await Promise.all(
                messages.map((m) =>
                    this.scrubConcurrency.run({
                        fn: () => this.scrubOne(m, controller.signal),
                        abortController: controller,
                    })
                )
            )
            return scrubbed.filter((image): image is ScrubbedImage => image !== null)
        } finally {
            clearTimeout(timer)
        }
    }

    private async scrubOne(m: Message, signal: AbortSignal): Promise<ScrubbedImage | null> {
        const ref = m.key?.toString('utf8')
        if (!ref || !isImageRef(ref) || !m.value) {
            return null
        }
        // Reject bytes whose hash doesn't match the key's (content integrity); an internal producer-only
        // topic, so a forged cross-team key is out of scope — this just guards corruption.
        const parsed = parseImageRef(ref)
        if (!parsed || hashImageBytes(m.value) !== parsed.hash) {
            ImageScrubConsumerMetrics.incMismatch()
            return null
        }
        const bytes = await this.scrubClient.scrub(m.value, signal)
        if (bytes === null) {
            ImageScrubConsumerMetrics.incSkipped()
            return null
        }
        ImageScrubConsumerMetrics.incScrubbed()
        return { pseudoTeam: parsed.pseudoTeam, hash: parsed.hash, bytes }
    }

    private shouldFlush(nowMs: number): boolean {
        if (this.buffer.length >= this.options.maxImages || this.bufferBytes >= this.options.maxBytes) {
            return true
        }
        const hasPending = this.buffer.length > 0 || this.pendingOffsets.size > 0
        return hasPending && nowMs - this.lastFlushMs >= this.options.flushIntervalMs
    }

    /** Write buffered images as one shard + index for the whole flush (pseudo_team lives in the index rows),
     *  then store the consumed offsets. Throws (without storing offsets, keeping the buffer) if the write
     *  fails, so the window replays. */
    public async flush(nowMs: number): Promise<void> {
        this.lastFlushMs = nowMs
        if (this.buffer.length > 0) {
            const { bytes } = await this.store.writeShard(this.buffer)
            ImageScrubConsumerMetrics.observeShard(this.buffer.length, bytes)
            this.buffer = []
            this.bufferBytes = 0
        }
        if (this.pendingOffsets.size > 0) {
            this.offsetStore.offsetsStore([...this.pendingOffsets.values()])
            this.pendingOffsets.clear()
        }
    }
}
