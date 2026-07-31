import { LibrdKafkaError, Message, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit, parseKafkaHeaders } from '~/common/kafka/consumer/consumer-v1'
import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { parseImageRef } from './content-ref'
import { ImageShardStore, ScrubbedImage } from './image-shard-store'
import { ImageScrubConsumerMetrics } from './metrics'
import { POISON_MIN_OTHER_SUCCESSES, ScrubAborted, ScrubClient, ScrubPoisoned } from './scrub-client'

export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

/**
 * Where an image the sidecar cannot process goes.
 *
 * Deliberately the original bytes rather than anything derived: the image was never scrubbed, so it
 * carries whatever PII it always did and must not reach the ML bucket, but discarding it would make
 * the sidecar bug behind it unreproducible. Parking it keeps both properties.
 */
export interface DeadLetterSink {
    park(image: { ref: string; bytes: Buffer; detail: Record<string, unknown> }): Promise<void>
}

/**
 * The librdkafka codes that mean "this partition is not ours to store an offset for".
 *
 * Which one a revoke produces depends on where in the revoke sequence the store lands: __STATE when
 * the partition object still exists but its offset store is stopped, __UNKNOWN_PARTITION when it is
 * gone from the assignment entirely, and the fenced/lost pair when the group has moved on without
 * us. All four have to be here: which one a given revoke produces is a matter of timing, so matching
 * a subset leaves the rest of the window exiting the process.
 */
/**
 * Names how many replays an image has already survived.
 *
 * Read on the way in and written back on the way out, so re-parking preserves it. If the count reset
 * on each pass, a replay run against a sidecar that still cannot handle the image would ping-pong it
 * between the two topics forever, spending scrub capacity on work already known to fail.
 */
export const REPLAY_COUNT_HEADER = 'replayCount'

const REVOKED_PARTITION_CODES = new Set([
    -172, // ERR__STATE
    -190, // ERR__UNKNOWN_PARTITION
    -142, // ERR__ASSIGNMENT_LOST
    -144, // ERR__FENCED
])

/** The batch index is what lets offsets advance across the messages planning skipped. */
interface PlannedScrub {
    index: number
    ref: string
    pseudoTeam: string
    hash: string
    value: Buffer
    /** Where this image came from, carried only so a parked one can be traced back to its source. */
    sourceTopic: string
    sourcePartition: number
    sourceOffset: number
    /**
     * How many times this image has already been replayed out of the dead-letter topic.
     *
     * Carried through so re-parking preserves it. Without that the count resets on every pass and a
     * replay run against a sidecar that still cannot handle the image ping-pongs it forever, which
     * is worse than leaving it parked: it spends scrub capacity on work already known to fail.
     */
    replayCount: number
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
    /**
     * The batch currently in flight, so shutdown can interrupt it.
     *
     * disconnect() waits on the running batch, and a batch waiting on a sidecar that is down waits
     * forever, so without this a graceful stop runs to the termination grace period and ends in a
     * SIGKILL. Aborting is safe: offsets are only recorded for images that finished, so whatever was
     * still in flight replays under the partition's next owner.
     */
    private activeBatch: AbortController | null = null
    private stopping = false
    /**
     * Set when a flush finds this pod no longer owns the partitions it is committing.
     *
     * Whatever is left of the batch belongs to another pod now, and scrubbing it anyway spends the
     * same saturated sidecar twice on one image and writes a second shard for a span the new owner
     * is already writing. That is load rising per unit of useful work exactly when capacity is what
     * is scarce, so the batch stops instead.
     */
    private partitionsRevoked = false
    /** Retired count of the running batch, read by the progress metric once it ends. */
    private retiredInBatch = 0

    constructor(
        private readonly store: ImageShardStore,
        private readonly offsetStore: OffsetStore,
        private readonly scrubClient: ScrubClient,
        private readonly options: ImageBatcherOptions,
        nowMs: number,
        private readonly deadLetters: DeadLetterSink | null = null
    ) {
        // 0 would admit nothing and spin the loop forever; NaN would skip it entirely, committing
        // offsets for unprocessed messages. Fail at boot rather than either.
        this.maxInFlight = Math.floor(options.scrubConcurrency)
        if (!Number.isInteger(this.maxInFlight) || this.maxInFlight < 1) {
            throw new Error(`scrubConcurrency must be a positive number, got ${options.scrubConcurrency}`)
        }
        // The poison gate can only ever see successes from slots running alongside the image it is
        // judging, because the batch holding it cannot finish and the pod cannot poll for more work
        // until it does. Concurrency at or below the threshold therefore makes the gate unreachable
        // and the pod deadlocks on the first unscrubbable image, so refuse to start instead.
        if (deadLetters && this.maxInFlight <= POISON_MIN_OTHER_SUCCESSES) {
            throw new Error(
                `scrubConcurrency must exceed ${POISON_MIN_OTHER_SUCCESSES} for dead-lettering to be reachable, got ${this.maxInFlight}`
            )
        }
        this.lastFlushMs = nowMs
        this.scrubConcurrency = new ConcurrencyController(this.maxInFlight)
        this.seenRefs = new RefDedupCache('image_scrub_consumer', options.dedupMaxRefs)
    }

    /** Interrupts the running batch so a graceful shutdown does not wait on an unresponsive sidecar. */
    public stop(): void {
        this.stopping = true
        this.activeBatch?.abort()
    }

    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        if (this.stopping) {
            return
        }
        // Skips resolve up front so the window only ever holds real work: a duplicate admitted into a
        // slot would occupy it and complete instantly, spending the pod's concurrency on no-ops.
        if (messages.length) {
            ImageScrubConsumerMetrics.observeBatchMessages(messages.length)
        }
        const planned = this.planBatch(messages)

        // A sliding window rather than fixed groups: every completion immediately admits the next
        // image, so the sidecar never waits on the slowest member of a group before being given more
        // work. Grouping would gate throughput on E[slowest of N] instead of E[mean], which on a
        // spread-out scrub-time distribution leaves a large share of the sidecar's cores idle.
        //
        // Admission is what bounds memory: scrubbed outputs can dwarf their inputs (a sub-MB input
        // can come back as a multi-MB full-resolution PNG), so submitting a whole poll batch at once
        // could hold gigabytes. Peak is ~maxBytes plus the outputs of one window.
        //
        // There is no time limit on the batch. A busy sidecar is waited on rather than given up on,
        // so the batch takes as long as the sidecar needs and the next consume() happens that much
        // later, which is the whole backpressure mechanism. Every message this batch took is finished
        // before any offset moves past it.
        const controller = new AbortController()
        this.activeBatch = controller
        this.partitionsRevoked = false
        const startedAt = performance.now()
        try {
            await this.scrubAndStage(messages, planned, controller, nowMs)
        } finally {
            // Empty polls arrive on a timer under callEachBatchWhenEmpty and would otherwise bury
            // the real distribution of both histograms in a zero bucket.
            if (planned.length > 0) {
                ImageScrubConsumerMetrics.observeBatchProgress(
                    this.retiredInBatch,
                    planned.length,
                    (performance.now() - startedAt) / 1000
                )
            }
            // Cleared here rather than on the success path: a throwing batch that left this set would
            // have shutdown abort a controller belonging to a batch that is already over.
            this.activeBatch = null
        }
    }

    private async scrubAndStage(
        messages: Message[],
        planned: PlannedScrub[],
        controller: AbortController,
        nowMs: number
    ): Promise<void> {
        let spanStart = 0
        let nextToSubmit = 0
        let retired = 0
        this.retiredInBatch = 0
        const settled = new Array<boolean>(planned.length).fill(false)
        const inFlight = new Map<number, Promise<SettledScrub>>()
        // Results wait here until their slot retires, so the buffer only ever holds images whose
        // offsets have been recorded. Without it a flush could persist an image while a still-running
        // predecessor kept its offset unrecorded, and a later batch failure would rewrite it under a
        // fresh shard key. Staged bytes count towards capacity, which is what bounds this.
        const staged = new Array<ScrubbedRef | null>(planned.length).fill(null)
        let stagedCount = 0
        let stagedBytes = 0

        while (nextToSubmit < planned.length || inFlight.size > 0) {
            while (
                nextToSubmit < planned.length &&
                inFlight.size < this.maxInFlight &&
                !this.overCapacity(stagedCount, stagedBytes)
            ) {
                inFlight.set(nextToSubmit, this.submitScrub(nextToSubmit, planned[nextToSubmit], controller))
                nextToSubmit++
            }
            // Only reachable over capacity with work left: flush to make room rather than spin.
            if (inFlight.size === 0) {
                await this.flushOrThrow(nowMs)
                if (this.partitionsRevoked) {
                    break
                }
                continue
            }

            const done = await Promise.race(inFlight.values())
            inFlight.delete(done.slot)
            if (done.error !== undefined) {
                // Shutdown is not a failure. Everything retired so far is flushed below and its
                // offsets are already recorded; the rest was never finished, so its offsets stay
                // unrecorded and it replays wherever the partition lands next.
                if (this.stopping) {
                    break
                }
                controller.abort() // one failure dooms the batch, so cancel the siblings still in flight
                ImageScrubConsumerMetrics.incBatchFailed('scrub')
                throw done.error
            }
            if (done.scrubbed) {
                staged[done.slot] = done.scrubbed
                stagedCount += 1
                stagedBytes += done.scrubbed.image.bytes.length
            }

            // Completions arrive out of order, so only the contiguous run from the front is safe to
            // commit: anything past a still-running image would commit an offset for work that has
            // not happened. The span also covers the skipped messages between retired entries, which
            // are done too and would otherwise replay forever. Offsets are only ever *stored* by a
            // flush, after the buffer holding these images is durably written.
            settled[done.slot] = true
            const retiredBefore = retired
            while (retired < planned.length && settled[retired]) {
                const ready = staged[retired]
                if (ready) {
                    this.buffer.push(ready.image)
                    this.bufferBytes += ready.image.bytes.length
                    // Marked here rather than on completion: a staged image is a local that a thrown
                    // batch discards, so a ref marked before retirement could be skipped on replay
                    // without ever having been persisted.
                    this.seenRefs.add(ready.ref)
                    staged[retired] = null
                    stagedCount -= 1
                    stagedBytes -= ready.image.bytes.length
                }
                retired++
                this.retiredInBatch = retired
            }
            if (retired > retiredBefore) {
                const spanEnd = planned[retired - 1].index + 1
                this.recordOffsets(messages.slice(spanStart, spanEnd))
                spanStart = spanEnd
            }
            if (this.overCapacity(stagedCount, stagedBytes)) {
                await this.flushOrThrow(nowMs)
            }
            if (this.partitionsRevoked) {
                controller.abort()
                break
            }
        }
        if (this.partitionsRevoked) {
            // Neither the offsets nor the shard belong to this pod any more. Writing it would only
            // duplicate what the partition's new owner is already producing, under a fresh key that
            // nothing later reconciles.
            this.buffer = []
            this.bufferBytes = 0
            this.pendingOffsets.clear()
            return
        }
        if (this.stopping) {
            // Deliberately no tail recordOffsets: past the last retired image nothing was finished,
            // and moving offsets over it here would lose exactly what the wait exists to protect.
            await this.flushOrThrow(nowMs)
            return
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
            planned.push({
                index,
                ref,
                pseudoTeam: parsed.pseudoTeam,
                hash: parsed.hash,
                value: m.value,
                sourceTopic: m.topic,
                sourcePartition: m.partition,
                sourceOffset: m.offset,
                replayCount: Number(parseKafkaHeaders(m.headers)[REPLAY_COUNT_HEADER] ?? 0) || 0,
            })
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
        let bytes: Buffer | null
        try {
            bytes = await this.scrubClient.scrub(planned.value, signal, planned.ref)
        } catch (error) {
            if (!(error instanceof ScrubPoisoned) || !this.deadLetters) {
                throw error
            }
            // Parked before the ref is marked and before the slot retires, so a failure to park
            // leaves the image exactly where it was: still unscrubbed, still uncommitted, still
            // waiting. Marking first would advance the offset over an image held nowhere.
            await this.parkUntilAccepted(planned, error, signal)
            logger.warn('☠️', 'image_scrub_dead_lettered', { ref: planned.ref, ...error.detail })
            this.seenRefs.add(planned.ref)
            ImageScrubConsumerMetrics.incDeadLettered(error.detail.reason)
            return null
        }
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

    /**
     * Publishes to the dead-letter topic, retrying until it is accepted or the caller hangs up.
     *
     * A park that cannot succeed leaves the image at the head of its partition, which is exactly the
     * behaviour this lane had before a dead-letter topic existed, and it is the only safe fallback:
     * the image is unscrubbed and held nowhere else, so the alternatives are discarding it or
     * advancing an offset over it. Letting the failure escape would be worse still, because the
     * Kafka loop exits on any batch error and the same image is redelivered on restart, turning a
     * misconfigured or undersized dead-letter topic into a crash loop across every pod in the lane.
     */
    private async parkUntilAccepted(
        planned: PlannedScrub,
        poisoned: ScrubPoisoned,
        signal: AbortSignal
    ): Promise<void> {
        for (let attempt = 0; ; attempt++) {
            if (signal.aborted) {
                throw new ScrubAborted('scrub batch aborted')
            }
            try {
                await this.deadLetters!.park({
                    ref: planned.ref,
                    bytes: planned.value,
                    detail: {
                        ...poisoned.detail,
                        pseudoTeam: planned.pseudoTeam,
                        hash: planned.hash,
                        sourceTopic: planned.sourceTopic,
                        sourcePartition: planned.sourcePartition,
                        sourceOffset: planned.sourceOffset,
                        // Carried back out, or the count restarts on every pass and the cap that
                        // bounds replay round trips never binds.
                        [REPLAY_COUNT_HEADER]: planned.replayCount,
                    },
                })
                return
            } catch (error) {
                ImageScrubConsumerMetrics.incDeadLetterFailed()
                logger.error('☠️', 'image_scrub_dead_letter_failed', {
                    ref: planned.ref,
                    bytes: planned.value.length,
                    attempts: attempt + 1,
                    error: String(error),
                })
                await new Promise((resolve) => setTimeout(resolve, Math.min(30_000, 500 * 2 ** attempt)).unref())
            }
        }
    }

    /** Staged results are counted so a slow slot holding back retirement still applies backpressure. */
    private overCapacity(stagedCount = 0, stagedBytes = 0): boolean {
        return (
            this.buffer.length + stagedCount >= this.options.maxImages ||
            this.bufferBytes + stagedBytes >= this.options.maxBytes
        )
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
            this.storeOffsetsUnlessRevoked([...this.pendingOffsets.values()])
            this.pendingOffsets.clear()
        }
    }

    /**
     * librdkafka refuses to store an offset for a partition this consumer no longer holds. A
     * rebalance during a batch is ordinary, and the shard is already on S3 by this point, so the only
     * thing lost is the record of how far we got: whoever picks the partition up rescrubs from the
     * last committed offset, which is the same at-least-once behaviour a restart produces. Letting it
     * propagate would exit the process, and a pod exiting is itself what triggers the next rebalance.
     *
     * The disconnected client throws a plain Error with no code at all, which is the same situation
     * arriving during shutdown, so it is tolerated on the same grounds.
     */
    private storeOffsetsUnlessRevoked(offsets: TopicPartitionOffset[]): void {
        try {
            this.offsetStore.offsetsStore(offsets)
        } catch (error) {
            const code = (error as LibrdKafkaError | undefined)?.code
            if (code !== undefined && !REVOKED_PARTITION_CODES.has(code)) {
                throw error
            }
            // Logged as well as counted: the counter says how many, and a lane that is quietly
            // rescrubbing the same span every batch needs the partitions to work that out.
            logger.warn('🔁', 'image_scrub_offsets_discarded', {
                error: String(error),
                code,
                partitions: offsets.map((o) => o.partition),
            })
            this.partitionsRevoked = true
            ImageScrubConsumerMetrics.incOffsetsDiscarded(offsets.length)
        }
    }
}
