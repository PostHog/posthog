import { Message, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import { ConcurrencyController } from '~/common/utils/concurrencyController'

import { isImageRef, parseImageRef } from './content-ref'
import { ImageShardStore, ScrubbedImage } from './image-shard-store'
import { ImageScrubConsumerMetrics } from './metrics'
import { ScrubClient } from './scrub-client'

export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

export interface ImageBatcherOptions {
    flushIntervalMs: number
    maxImages: number
    maxBytes: number
    scrubConcurrency: number
    maxBatchScrubMs: number
}

export class ImageBatcher {
    private buffer: ScrubbedImage[] = []
    private bufferBytes = 0
    private pendingOffsets = new Map<string, TopicPartitionOffset>()
    private lastFlushMs: number
    private readonly chunkSize: number
    private readonly scrubConcurrency: ConcurrencyController

    constructor(
        private readonly store: ImageShardStore,
        private readonly offsetStore: OffsetStore,
        private readonly scrubClient: ScrubClient,
        private readonly options: ImageBatcherOptions,
        nowMs: number
    ) {
        // The concurrency doubles as the chunk stride below; 0 would spin the loop forever and NaN
        // would skip it entirely (committing offsets for unprocessed messages), so fail at boot.
        this.chunkSize = Math.floor(options.scrubConcurrency)
        if (!Number.isInteger(this.chunkSize) || this.chunkSize < 1) {
            throw new Error(`scrubConcurrency must be a positive number, got ${options.scrubConcurrency}`)
        }
        this.lastFlushMs = nowMs
        this.scrubConcurrency = new ConcurrencyController(this.chunkSize)
    }

    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        // Scrub in concurrency-sized chunks with the capacity bounds applied between chunks: scrubbed
        // outputs can dwarf their inputs (a sub-MB input can come back as a multi-MB full-resolution
        // PNG), so retaining a whole poll batch of them before the first bound check can hold
        // gigabytes. Peak memory is now ~maxBytes plus one chunk's outputs.
        //
        // The deadline covers scrub time only: the timer is armed per chunk with the remaining
        // budget and disarmed before any mid-batch flush, so slow-but-succeeding S3 writes (each
        // bounded by their own timeout) can't burn the scrub budget and turn into an abort/replay
        // loop misattributed to the sidecar.
        const controller = new AbortController()
        let scrubBudgetMs = this.options.maxBatchScrubMs
        for (let i = 0; i < messages.length; i += this.chunkSize) {
            const chunk = messages.slice(i, i + this.chunkSize)
            const chunkStartMs = performance.now()
            const timer = setTimeout(() => controller.abort(), scrubBudgetMs)
            let scrubbed: ScrubbedImage[]
            try {
                scrubbed = await this.scrubChunk(chunk, controller)
            } catch (e) {
                ImageScrubConsumerMetrics.incBatchFailed('scrub')
                throw e
            } finally {
                clearTimeout(timer)
            }
            scrubBudgetMs -= performance.now() - chunkStartMs
            for (const image of scrubbed) {
                this.buffer.push(image)
                this.bufferBytes += image.bytes.length
            }
            // Advance offsets per completed chunk (even all-skipped ones, or skipped messages
            // replay forever). They are only ever *stored* by a flush, after the buffer — which
            // holds exactly these chunks' images — is durably written. A mid-batch flush thereby
            // records the progress it persisted: a later failure in this batch replays only from
            // the flush, instead of re-writing another copy of the flushed shard per replay.
            for (const offset of findOffsetsToCommit(chunk)) {
                this.pendingOffsets.set(`${offset.topic}:${offset.partition}`, offset)
            }
            if (this.overCapacity()) {
                await this.flushOrThrow(nowMs)
            }
        }
        if (this.shouldFlush(nowMs)) {
            await this.flushOrThrow(nowMs)
        }
    }

    private async scrubChunk(messages: Message[], controller: AbortController): Promise<ScrubbedImage[]> {
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
        } catch (e) {
            controller.abort() // one failure dooms the batch, so cancel the siblings still in flight
            throw e
        }
    }

    private async flushOrThrow(nowMs: number): Promise<void> {
        try {
            await this.flush(nowMs)
        } catch (e) {
            ImageScrubConsumerMetrics.incBatchFailed('write')
            throw e
        }
    }

    private async scrubOne(m: Message, signal: AbortSignal): Promise<ScrubbedImage | null> {
        const ref = m.key?.toString('utf8')
        if (!ref || !isImageRef(ref) || !m.value) {
            ImageScrubConsumerMetrics.incInvalidKey()
            return null
        }
        // The ref's hash is a producer-side per-team HMAC; this consumer doesn't hold the key and
        // trusts the producer (the topic's only writer) that the key names these bytes.
        const parsed = parseImageRef(ref)
        if (!parsed) {
            ImageScrubConsumerMetrics.incInvalidKey()
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

    private overCapacity(): boolean {
        return this.buffer.length >= this.options.maxImages || this.bufferBytes >= this.options.maxBytes
    }

    private shouldFlush(nowMs: number): boolean {
        if (this.overCapacity()) {
            return true
        }
        const hasPending = this.buffer.length > 0 || this.pendingOffsets.size > 0
        return hasPending && nowMs - this.lastFlushMs >= this.options.flushIntervalMs
    }

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
