import { Message, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { imageRef, isImageRef, parseImageRef } from './content-ref'
import { ImageShardStore, ScrubbedImage } from './image-shard-store'
import { ImageScrubConsumerMetrics } from './metrics'
import { ScrubClient } from './scrub-client'

export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

/** A message that survived planning, carrying its batch index so offsets can advance over the skips. */
interface PlannedScrub {
    index: number
    pseudoTeam: string
    hash: string
    value: Buffer
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
     * Refs this pod has already scrubbed, as a best-effort stand-in for "these bytes are already in
     * the ML bucket" — shards pack many images per object, so there is no per-hash key to ask S3
     * about. The topic is keyed by ref, so every copy of an image lands on the same partition and
     * therefore this pod: within its capacity the answer is exact, and past it we simply rescrub.
     * Entries are added once an image is buffered for a shard write, so a marked ref is always one
     * this pod holds or has written — a batch that throws keeps its buffer, and a rebalance without
     * a restart can no longer skip a ref it never persisted.
     *
     * This only ever saves work that intra-batch dedup did not already save; sizing it is a
     * throughput question, not a correctness one, and the cache's capacity probe metric is what
     * says whether the size is actually costing us hits.
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
        // Resolve every skip before chunking. A duplicate left in the chunk still consumes a
        // concurrency slot and resolves as a no-op, so a chunk finishes as soon as its one distinct
        // image does: with repeats outnumbering distinct images the batch serializes behind the
        // chunk barriers and the pod runs one scrub at a time whatever scrubConcurrency says.
        ImageScrubConsumerMetrics.observeBatchMessages(messages.length)
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
                this.seenRefs.add(imageRef(image.pseudoTeam, image.hash))
            }
            // Advance offsets per completed chunk, across the whole span of the batch it consumed —
            // the skipped messages sitting between its entries are done too, and would otherwise
            // replay forever. Offsets are only ever *stored* by a flush, after the buffer — which
            // holds exactly these chunks' images — is durably written. A mid-batch flush thereby
            // records the progress it persisted: a later failure in this batch replays only from
            // the flush, instead of re-writing another copy of the flushed shard per replay.
            const spanEnd = chunk[chunk.length - 1].index + 1
            this.recordOffsets(messages.slice(spanStart, spanEnd))
            spanStart = spanEnd
            if (this.overCapacity()) {
                await this.flushOrThrow(nowMs)
            }
        }
        // Whatever trails the last scrubbed message is skips only (and a wholly-skipped batch is all
        // trailer), so it needs the same treatment or those offsets never move.
        this.recordOffsets(messages.slice(spanStart))
        if (this.shouldFlush(nowMs)) {
            await this.flushOrThrow(nowMs)
        }
    }

    /**
     * Decide, for a whole batch at once, which messages actually reach the sidecar: the first
     * occurrence of each ref, minus anything already scrubbed. Intra-batch dedup is unconditional —
     * it needs no retained state, so unlike [[seenRefs]] it cannot be sized wrong or turned off.
     */
    private planBatch(messages: Message[]): PlannedScrub[] {
        const planned: PlannedScrub[] = []
        const batchRefs = new Set<string>()
        for (const [index, m] of messages.entries()) {
            const ref = m.key?.toString('utf8')
            if (!ref || !isImageRef(ref) || !m.value) {
                ImageScrubConsumerMetrics.incInvalidKey()
                continue
            }
            // The ref's hash is a producer-side per-team HMAC; this consumer doesn't hold the key and
            // trusts the producer (the topic's only writer) that the key names these bytes.
            const parsed = parseImageRef(ref)
            if (!parsed) {
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
            planned.push({ index, pseudoTeam: parsed.pseudoTeam, hash: parsed.hash, value: m.value })
        }
        return planned
    }

    private recordOffsets(messages: Message[]): void {
        for (const offset of findOffsetsToCommit(messages)) {
            this.pendingOffsets.set(`${offset.topic}:${offset.partition}`, offset)
        }
    }

    private async scrubChunk(planned: PlannedScrub[], controller: AbortController): Promise<ScrubbedImage[]> {
        try {
            const scrubbed = await Promise.all(
                planned.map((p) =>
                    this.scrubConcurrency.run({
                        fn: () => this.scrubOne(p, controller.signal),
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

    private async scrubOne(planned: PlannedScrub, signal: AbortSignal): Promise<ScrubbedImage | null> {
        const bytes = await this.scrubClient.scrub(planned.value, signal)
        if (bytes === null) {
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
