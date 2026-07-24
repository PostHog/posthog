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

/** Carries the window slot so a completion can be matched back to its position, which is what
 *  lets offsets retire in order even though scrubs finish out of order. */
interface SettledScrub {
    slot: number
    scrubbed: ScrubbedRef | null
    error?: unknown
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
    private readonly maxInFlight: number
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
        // 0 would admit nothing and spin the loop forever; NaN would skip it entirely, committing
        // offsets for unprocessed messages. Fail at boot rather than either.
        this.maxInFlight = Math.floor(options.scrubConcurrency)
        if (!Number.isInteger(this.maxInFlight) || this.maxInFlight < 1) {
            throw new Error(`scrubConcurrency must be a positive number, got ${options.scrubConcurrency}`)
        }
        this.lastFlushMs = nowMs
        this.scrubConcurrency = new ConcurrencyController(this.maxInFlight)
        this.seenRefs = new RefDedupCache('image_scrub_consumer', options.dedupMaxRefs)
    }

    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        // Skips resolve up front so the window only ever holds real work: a duplicate admitted into a
        // slot would occupy it and complete instantly, spending the pod's concurrency on no-ops.
        if (messages.length) {
            ImageScrubConsumerMetrics.observeBatchMessages(messages.length)
        }
        const planned = this.planBatch(messages)

        // A sliding window rather than fixed groups: every completion immediately admits the next
        // image, so the sidecar never waits on the slowest member of a group before being given more
        // work. Grouping used to gate throughput on E[slowest of N] instead of E[mean], which on a
        // spread-out scrub-time distribution leaves a large share of the sidecar's cores idle.
        //
        // Admission is what bounds memory: scrubbed outputs can dwarf their inputs (a sub-MB input
        // can come back as a multi-MB full-resolution PNG), so submitting a whole poll batch at once
        // could hold gigabytes. Peak is ~maxBytes plus the outputs of one window.
        //
        // The deadline covers scrub time only: the timer is armed around each wait and the elapsed
        // time charged to the budget, so slow-but-succeeding S3 writes (each bounded by their own
        // timeout) can't burn the scrub budget and turn into an abort/replay loop misattributed to
        // the sidecar.
        const controller = new AbortController()
        let scrubBudgetMs = this.options.maxBatchScrubMs
        let spanStart = 0
        let nextToSubmit = 0
        let retired = 0
        const settled = new Array<boolean>(planned.length).fill(false)
        const inFlight = new Map<number, Promise<SettledScrub>>()

        while (nextToSubmit < planned.length || inFlight.size > 0) {
            while (nextToSubmit < planned.length && inFlight.size < this.maxInFlight && !this.overCapacity()) {
                inFlight.set(nextToSubmit, this.submitScrub(nextToSubmit, planned[nextToSubmit], controller))
                nextToSubmit++
            }
            // Only reachable over capacity with work left: flush to make room rather than spin.
            if (inFlight.size === 0) {
                await this.flushOrThrow(nowMs)
                continue
            }

            const waitStartMs = performance.now()
            const timer = setTimeout(() => controller.abort(), scrubBudgetMs)
            let done: SettledScrub
            try {
                done = await Promise.race(inFlight.values())
            } finally {
                clearTimeout(timer)
                scrubBudgetMs -= performance.now() - waitStartMs
            }
            inFlight.delete(done.slot)
            if (done.error !== undefined) {
                controller.abort() // one failure dooms the batch, so cancel the siblings still in flight
                ImageScrubConsumerMetrics.incBatchFailed('scrub')
                throw done.error
            }
            if (done.scrubbed) {
                this.buffer.push(done.scrubbed.image)
                this.bufferBytes += done.scrubbed.image.bytes.length
                this.seenRefs.add(done.scrubbed.ref)
            }

            // Completions arrive out of order, so only the contiguous run from the front is safe to
            // commit: anything past a still-running image would commit an offset for work that has
            // not happened. The span also covers the skipped messages between retired entries, which
            // are done too and would otherwise replay forever. Offsets are only ever *stored* by a
            // flush, after the buffer holding these images is durably written.
            settled[done.slot] = true
            const retiredBefore = retired
            while (retired < planned.length && settled[retired]) {
                retired++
            }
            if (retired > retiredBefore) {
                const spanEnd = planned[retired - 1].index + 1
                this.recordOffsets(messages.slice(spanStart, spanEnd))
                spanStart = spanEnd
            }
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

    /**
     * Failures resolve rather than reject so the caller can race the whole window without the losing
     * promises becoming unhandled rejections when the batch aborts.
     */
    private submitScrub(slot: number, p: PlannedScrub, controller: AbortController): Promise<SettledScrub> {
        return this.scrubConcurrency
            .run({
                fn: () => this.scrubOne(p, controller.signal),
                abortController: controller,
            })
            .then(
                (image): SettledScrub => ({ slot, scrubbed: image ? { ref: p.ref, image } : null }),
                (error): SettledScrub => ({ slot, scrubbed: null, error: error ?? new Error('scrub failed') })
            )
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
