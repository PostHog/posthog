import { Message, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { parseImageRef } from './content-ref'
import { ImageShardStore, ScrubbedImage } from './image-shard-store'
import { ImageScrubConsumerMetrics } from './metrics'
import { ScrubClient } from './scrub-client'

export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

/** The batch index is what lets offsets advance across the messages planning skipped. */
interface PlannedScrub {
    index: number
    ref: string
    pseudoTeam: string
    hash: string
    value: Buffer
}

interface ScrubbedRef {
    ref: string
    image: ScrubbedImage
}

export interface ImageBatcherOptions {
    flushIntervalMs: number
    maxImages: number
    maxBytes: number
    scrubConcurrency: number
    maxBatchScrubMs: number
    dedupMaxRefs: number
}

export class ImageBatcher {
    private buffer: ScrubbedImage[] = []
    private bufferBytes = 0
    private pendingOffsets = new Map<string, TopicPartitionOffset>()
    private lastFlushMs: number
    private readonly chunkSize: number
    private readonly scrubConcurrency: ConcurrencyController
    /**
     * Refs this pod has resolved, either by buffering the scrubbed bytes or by having the sidecar
     * permanently reject them. A best-effort stand-in for asking S3 "are these bytes already in the
     * bucket", which shards cannot answer: they pack many images per object, so no per-hash key
     * exists. The topic is keyed by ref, so every copy of an image reaches this same pod and within
     * capacity the answer is exact; past it we simply rescrub. Marking a scrubbed ref only after its
     * buffer push is what stops a rebalance without a restart from skipping a ref it never persisted,
     * since a batch that throws keeps its buffer. Sizing is a throughput question, not a correctness
     * one.
     */
    private readonly seenRefs: RefDedupCache

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
        this.seenRefs = new RefDedupCache('image_scrub_consumer', options.dedupMaxRefs)
    }

    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        // Skips must resolve before chunking: a duplicate left in a chunk still holds a concurrency
        // slot and completes instantly, so the chunk ends with its one distinct image and the batch
        // serializes behind the barriers, running one scrub at a time whatever scrubConcurrency says.
        if (messages.length) {
            ImageScrubConsumerMetrics.observeBatchMessages(messages.length)
        }
        const planned = this.planBatch(messages)

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
        let spanStart = 0
        for (let i = 0; i < planned.length; i += this.chunkSize) {
            const chunk = planned.slice(i, i + this.chunkSize)
            const chunkStartMs = performance.now()
            const timer = setTimeout(() => controller.abort(), scrubBudgetMs)
            let scrubbed: ScrubbedRef[]
            try {
                scrubbed = await this.scrubChunk(chunk, controller)
            } catch (e) {
                ImageScrubConsumerMetrics.incBatchFailed('scrub')
                throw e
            } finally {
                clearTimeout(timer)
            }
            scrubBudgetMs -= performance.now() - chunkStartMs
            for (const { ref, image } of scrubbed) {
                this.buffer.push(image)
                this.bufferBytes += image.bytes.length
                this.seenRefs.add(ref)
            }
            // The span also covers the skipped messages between this chunk's entries, which are done
            // too and would otherwise replay forever. Offsets are only ever *stored* by a flush,
            // after the buffer holding these images is durably written, so a mid-batch flush records
            // exactly the progress it persisted and a later failure replays only from there.
            const spanEnd = chunk[chunk.length - 1].index + 1
            this.recordOffsets(messages.slice(spanStart, spanEnd))
            spanStart = spanEnd
            if (this.overCapacity()) {
                await this.flushOrThrow(nowMs)
            }
        }
        // A batch whose tail is all skips, or which is nothing but skips, still has to move offsets.
        this.recordOffsets(messages.slice(spanStart))
        if (this.shouldFlush(nowMs)) {
            await this.flushOrThrow(nowMs)
        }
    }

    /** Retains nothing between batches, so unlike [[seenRefs]] this dedup cannot be sized wrong or disabled. */
    private planBatch(messages: Message[]): PlannedScrub[] {
        const planned: PlannedScrub[] = []
        const batchRefs = new Set<string>()
        for (const [index, m] of messages.entries()) {
            const ref = m.key?.toString('utf8')
            // The ref's hash is a producer-side per-team HMAC; this consumer doesn't hold the key and
            // trusts the producer (the topic's only writer) that the key names these bytes.
            const parsed = ref ? parseImageRef(ref) : null
            if (!ref || !parsed || !m.value) {
                ImageScrubConsumerMetrics.incInvalidKey()
                continue
            }
            if (batchRefs.has(ref)) {
                ImageScrubConsumerMetrics.incDeduped('batch')
                continue
            }
            batchRefs.add(ref)
            if (this.seenRefs.has(ref)) {
                ImageScrubConsumerMetrics.incDeduped('pod')
                continue
            }
            planned.push({ index, ref, pseudoTeam: parsed.pseudoTeam, hash: parsed.hash, value: m.value })
        }
        return planned
    }

    private recordOffsets(messages: Message[]): void {
        for (const offset of findOffsetsToCommit(messages)) {
            this.pendingOffsets.set(`${offset.topic}:${offset.partition}`, offset)
        }
    }

    private async scrubChunk(planned: PlannedScrub[], controller: AbortController): Promise<ScrubbedRef[]> {
        try {
            const scrubbed = await Promise.all(
                planned.map((p) =>
                    this.scrubConcurrency.run({
                        fn: () =>
                            this.scrubOne(p, controller.signal).then((image) => (image ? { ref: p.ref, image } : null)),
                        abortController: controller,
                    })
                )
            )
            return scrubbed.filter((entry): entry is ScrubbedRef => entry !== null)
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

    private async scrubOne(planned: PlannedScrub, signal: AbortSignal): Promise<ScrubbedImage | null> {
        const bytes = await this.scrubClient.scrub(planned.value, signal)
        if (bytes === null) {
            // Null is only ever a 422/413, a verdict on the content itself, so no retry can succeed.
            // Marking it stops every later copy from re-earning the same rejection, and there is
            // nothing pending to persist, so this needs none of the care the success path does.
            this.seenRefs.add(planned.ref)
            ImageScrubConsumerMetrics.incSkipped()
            return null
        }
        ImageScrubConsumerMetrics.incScrubbed()
        return { pseudoTeam: planned.pseudoTeam, hash: planned.hash, bytes }
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
