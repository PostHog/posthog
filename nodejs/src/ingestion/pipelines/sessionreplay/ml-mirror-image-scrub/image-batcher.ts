import { LibrdKafkaError, Message, TopicPartitionOffset } from 'node-rdkafka'
import { setTimeout as waitForRetry } from 'node:timers/promises'
import pLimit from 'p-limit'

import { findOffsetsToCommit, parseKafkaHeaders } from '~/common/kafka/consumer/consumer-v1'
import { ConcurrencyController } from '~/common/utils/concurrencyController'
import { logger } from '~/common/utils/logger'
import { MlKeyManager } from '~/ingestion/pipelines/sessionreplay/ml-mirror/keys/runtime'
import {
    INGESTION_VERSION_HEADER,
    imageKeyId,
    tableKeyString,
} from '~/ingestion/pipelines/sessionreplay/ml-mirror/keys/schema'
import { MlDecodedMessage, ingestionVersion } from '~/ingestion/pipelines/sessionreplay/ml-mirror/keys/transport'
import { RefDedupCache } from '~/ingestion/pipelines/sessionreplay/shared/ref-dedup-cache'

import { parseImageRef } from './content-ref'
import { ImageShardStore, ScrubbedImage, ScrubbedUrlImage } from './image-shard-store'
import {
    CAPTURE_TIMESTAMP_HEADER,
    CONTENT_ENCODING_HEADER,
    CONTENT_TYPE_HEADER,
    InvalidImageTransportError,
    prepareFetchedImage,
} from './image-transport'
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
    park(image: {
        ref: string
        bytes: Buffer
        headers: Record<string, string>
        detail: Record<string, unknown>
    }): Promise<void>
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
    sessionMonth?: string
    datasetVersion?: 2 | 3
    encryptedValue?: Buffer
    index: number
    ref: string
    teamId?: string
    pseudoTeam?: string
    hash: string
    source: 'bytes' | 'url'
    value: Buffer
    transportHeaders: Record<string, string>
    capturedAtMs?: number
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
    source: 'bytes' | 'url'
    image: ScrubbedImage | ScrubbedUrlImage
    capturedAtMs?: number
}

/** Carries the window slot so a completion can be matched back to its position, which is what
 *  lets offsets retire in order even though scrubs finish out of order. */
interface SettledScrub {
    slot: number
    scrubbed: ScrubbedRef | null
    error?: unknown
}

export interface ImageBatcherOptions {
    /** How long scrubbed images accumulate before a hand-off, so images of one team-month across several polls share a shard. */
    flushIntervalMs: number
    maxImages: number
    maxBytes: number
    scrubConcurrency: number
    dedupMaxRefs: number
}

/**
 * S3 objects in flight per hand-off: shard groups and URL images alike.
 *
 * A batch's images spread over as many shard groups as it has team-months, which is most of them,
 * so written one after another the groups cost a round trip each and the sidecar idles for the sum.
 * Written together they cost about one. Bounded so that, together with the store's own lookup
 * limiter, a burst stays under the S3 client's socket pool, and separate from the scrub concurrency
 * so a write never takes a slot from the next batch.
 */
export const WRITE_CONCURRENCY = 8

/**
 * Hand-offs the write lane may hold: one writing, one queued. A batch that hands off while both
 * are held waits for the oldest to finish before it continues.
 *
 * Writes run behind the scrub of the next batches, so an S3 slowdown would otherwise queue
 * hand-offs without limit and hold their images in memory. The wait bounds resident scrubbed output
 * at two hand-offs plus what the running batch has staged, and the hand-off being written is copied
 * twice more (Buffer.concat, then the encryption envelope). That multiplier is what the MAX_BYTES
 * comment in ml-mirror/config.ts states, so change both together.
 */
const MAX_WRITES_IN_FLIGHT = 2

/**
 * What a batch hands to the write lane: images whose offsets retired in order, and those offsets.
 * The offsets are stored only once every image here is durable, so they travel together.
 */
interface WriteHandoff {
    images: ScrubbedRef[]
    offsets: TopicPartitionOffset[]
}

/**
 * Waits for every write, then raises the first failure. A lane failure exits the process, and a
 * sibling write still in flight at that point leaves a partial shard behind that nothing indexes.
 */
async function settleAll(writes: Promise<void>[]): Promise<void> {
    const failed = (await Promise.allSettled(writes)).find(
        (result): result is PromiseRejectedResult => result.status === 'rejected'
    )
    if (failed) {
        throw failed.reason
    }
}

export class ImageBatcher {
    /** Retired images of the running batch that no hand-off has taken yet. */
    private outgoing: ScrubbedRef[] = []
    private outgoingBytes = 0
    private outgoingOffsets = new Map<string, TopicPartitionOffset>()
    /**
     * When an interval-driven hand-off last happened. Undefined until the first one, so the first
     * batch does not wait a whole interval. Capacity hand-offs do not reset it: the batch clock is
     * read once per batch, so a reset would leave the tail behind a capacity hand-off waiting for a
     * later batch with its offsets uncommitted.
     */
    private lastHandOffMs: number | undefined
    /**
     * Writes hand-offs one at a time, in the order the batches retired them.
     *
     * The order is what makes a failure safe: a hand-off stores its offsets only after its own
     * images are durable, and the first failure poisons the lane so nothing behind it can store an
     * offset past the images that were never written. The process then exits on the next batch and
     * replays from the last stored offset.
     */
    private readonly writeLane = pLimit(1)
    private readonly writeLimiter = pLimit(WRITE_CONCURRENCY)
    private writesInFlight: Promise<void>[] = []
    private writeFailure: unknown
    private activeBatchSettled: Promise<void> = Promise.resolve()
    private readonly maxInFlight: number
    private readonly scrubConcurrency: ConcurrencyController
    /**
     * Content-addressed refs this pod has resolved, either by buffering the scrubbed bytes or by
     * having the sidecar permanently reject them. URL refs are absent because their bytes can change
     * between recrawls. A best-effort stand-in for asking S3 "are these bytes already in the bucket",
     * which shards cannot answer: they pack many images per object, so no per-hash key exists. The
     * topic is keyed by ref, so every copy of an inline image reaches this same pod and within capacity
     * the answer is exact; past it we simply rescrub. Marking a scrubbed ref only once it is staged for a
     * hand-off is what stops a rebalance without a restart from skipping a ref it never persisted, since
     * a batch that throws discards what it staged. Sizing is a throughput question, not a correctness one.
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
     * Set when a write finds this pod no longer owns the partitions it is committing.
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
        private readonly deadLetters: DeadLetterSink | null = null,
        private readonly keyManager?: MlKeyManager
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
        this.scrubConcurrency = new ConcurrencyController(this.maxInFlight)
        this.seenRefs = new RefDedupCache('image_scrub_consumer', options.dedupMaxRefs)
    }

    /**
     * Interrupts the running batch so a graceful shutdown does not wait on an unresponsive sidecar,
     * then waits for the write lane, so the images that did finish reach S3 and their offsets are
     * stored while the consumer is still connected to commit them. Resolves either way: a write
     * that failed was already logged by the lane, and there is no batch left to raise it through.
     */
    public async stop(): Promise<void> {
        this.stopping = true
        this.activeBatch?.abort()
        await this.activeBatchSettled
        try {
            await this.drain()
        } catch (error) {
            logger.error('🔥', 'image_scrub_write_failed_during_shutdown', { error: String(error) })
        }
    }

    /** Resolves once every hand-off taken so far is written and its offsets stored; rejects with the lane's failure. */
    public async drain(): Promise<void> {
        await Promise.all(this.writesInFlight)
        // A hand-off that failed before this call has already left the list, so the list alone cannot report it.
        if (this.writeFailure !== undefined) {
            throw this.writeFailure
        }
    }

    public async handleBatch(messages: Message[], nowMs = Date.now()): Promise<void> {
        if (this.stopping) {
            return
        }
        // Raised here rather than swallowed by the lane, because the Kafka loop exits the process on
        // a batch error and that exit is what replays the unwritten images from the last stored offset.
        if (this.writeFailure !== undefined) {
            throw this.writeFailure
        }
        const controller = new AbortController()
        this.activeBatch = controller
        this.partitionsRevoked = false
        const running = this.handleActiveBatch(messages, controller, nowMs)
        this.activeBatchSettled = running.then(
            () => undefined,
            () => undefined
        )
        try {
            await running
        } catch (error) {
            if (this.stopping && error instanceof ScrubAborted) {
                return
            }
            // The Kafka loop disconnects the client as soon as this rejects, before shutdown reaches
            // stop(), so a hand-off still writing would find no client to store its offsets with and
            // its shards would be written again after the restart. A poisoned lane has nothing left
            // that could store, so its own failure is raised straight away.
            if (error !== this.writeFailure) {
                // Logged rather than raised, so the batch failure stays the one the process exits on,
                // and the storage failure behind it is still on record for whoever reads the logs.
                await this.drain().catch((writeError) =>
                    logger.error('🔥', 'image_scrub_write_failed_behind_failed_batch', { error: String(writeError) })
                )
            }
            throw error
        } finally {
            // Cleared here rather than on the success path: a throwing batch that left this set would
            // have shutdown abort a controller belonging to a batch that is already over.
            this.activeBatch = null
        }
    }

    private async handleActiveBatch(messages: Message[], controller: AbortController, nowMs: number): Promise<void> {
        // Skips resolve up front so the window only ever holds real work: a duplicate admitted into a
        // slot would occupy it and complete instantly, spending the pod's concurrency on no-ops.
        if (messages.length) {
            ImageScrubConsumerMetrics.observeBatchMessages(messages.length)
        }
        const decoded: MlDecodedMessage[] = this.keyManager
            ? await this.keyManager.kafka.read(messages, { bindKafkaKey: true })
            : messages.map((message) => {
                  const version = ingestionVersion(message)
                  if (version === 2) {
                      throw new Error('ML v2 images require key manager configuration')
                  }
                  return { message, original: message, version, invalid: undefined }
              })
        const decodedValid = decoded.filter((entry) => !entry.invalid && !entry.legacy)
        const v2 = decodedValid.filter((entry) => entry.version === 2).length
        ImageScrubConsumerMetrics.incrementVersion('2', v2)
        ImageScrubConsumerMetrics.incrementVersion('1', decodedValid.length - v2)
        for (const entry of decoded.filter((entry) => entry.invalid)) {
            if (!this.deadLetters) {
                throw new Error('An invalid ML image record requires a dead-letter destination')
            }
            await this.parkImageUntilAccepted(
                {
                    ref: entry.original.key?.toString() ?? '',
                    bytes: entry.original.value ?? Buffer.alloc(0),
                    headers: parseKafkaHeaders(entry.original.headers),
                    detail: {
                        reason: 'invalid_record',
                        sourceTopic: entry.original.topic,
                        sourcePartition: entry.original.partition,
                        sourceOffset: entry.original.offset,
                    },
                },
                controller.signal
            )
        }
        const byOriginal = new Map(decodedValid.map((entry) => [entry.original, entry.message]))
        const planned = this.planBatch(
            messages.map((message) => byOriginal.get(message) ?? { ...message, value: null })
        )
        for (const item of planned) {
            if (item.sessionMonth !== undefined) {
                item.encryptedValue = messages[item.index].value ?? undefined
            }
        }

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
        const startedAt = performance.now()
        if (planned.length > 0) {
            ImageScrubConsumerMetrics.startBatch()
        }
        try {
            await this.scrubAndStage(messages, planned, controller, nowMs)
        } finally {
            // Empty polls arrive on a timer under callEachBatchWhenEmpty and would otherwise bury
            // the real distribution of both histograms in a zero bucket.
            if (planned.length > 0) {
                ImageScrubConsumerMetrics.finishBatch()
                ImageScrubConsumerMetrics.observeBatchProgress(
                    this.retiredInBatch,
                    planned.length,
                    (performance.now() - startedAt) / 1000
                )
            }
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
        // offsets have been recorded. Without it a write could persist an image while a still-running
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
            // Only reachable over capacity with work left: hand off to make room rather than spin.
            if (inFlight.size === 0) {
                await this.handOffOrAbort(controller)
                if (this.partitionsRevoked) {
                    break
                }
                continue
            }

            const done = await Promise.race(inFlight.values())
            inFlight.delete(done.slot)
            if (done.error !== undefined) {
                // Shutdown is not a failure. Everything retired so far is handed off below and its
                // offsets are already recorded; the rest was never finished, so its offsets stay
                // unrecorded and it replays wherever the partition lands next.
                if (this.stopping) {
                    break
                }
                controller.abort() // one failure dooms the batch, so cancel the siblings still in flight
                ImageScrubConsumerMetrics.incBatchFailed('scrub')
                throw done.error
            }
            // A hand-off that failed behind this batch: nothing this batch retires can be stored past
            // the images it never wrote, so stop scrubbing now rather than at the end of the batch.
            if (this.writeFailure !== undefined) {
                controller.abort()
                throw this.writeFailure
            }
            if (done.scrubbed) {
                staged[done.slot] = done.scrubbed
                stagedCount += 1
                stagedBytes += done.scrubbed.image.bytes.length
            }

            // Completions arrive out of order, so only the contiguous run from the front is safe to
            // commit: anything past a still-running image would commit an offset for work that has
            // not happened. The span also covers the skipped messages between retired entries, which
            // are done too and would otherwise replay forever. Offsets are only ever *stored* by the
            // write lane, after the hand-off holding these images is durably written.
            settled[done.slot] = true
            const retiredBefore = retired
            while (retired < planned.length && settled[retired]) {
                const ready = staged[retired]
                if (ready) {
                    this.stageOutgoing(ready)
                    // Marked here rather than on completion: a staged image is a local that a thrown
                    // batch discards, so a ref marked before retirement could be skipped on replay
                    // without ever having been persisted.
                    if (ready.source === 'bytes') {
                        this.seenRefs.add(ready.ref)
                    }
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
                await this.handOffOrAbort(controller)
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
            this.forgetUnwritten(this.outgoing)
            this.outgoing = []
            this.outgoingBytes = 0
            this.outgoingOffsets.clear()
            return
        }
        if (this.stopping) {
            // Deliberately no tail recordOffsets: past the last retired image nothing was finished,
            // and moving offsets over it here would lose exactly what the wait exists to protect.
            await this.handOff()
            return
        }
        // A batch whose tail is all skips, or which is nothing but skips, still has to move offsets.
        this.recordOffsets(messages.slice(spanStart))
        // nowMs is the batch's start. A batch that crosses the interval leaves its tail to the next
        // poll, and empty polls run this check too, so that is at most one poll timeout later.
        if (this.lastHandOffMs === undefined || nowMs - this.lastHandOffMs >= this.options.flushIntervalMs) {
            this.lastHandOffMs = nowMs
            await this.handOff()
        }
    }

    /** A rejected wait on the lane ends the batch like a failed scrub does: the sidecar must not keep working on results nobody will read. */
    private async handOffOrAbort(controller: AbortController): Promise<void> {
        try {
            await this.handOff()
        } catch (error) {
            controller.abort()
            throw error
        }
    }

    /**
     * Moves everything retired so far to the write lane and returns as soon as the lane has room,
     * so the scrub of the next batch overlaps the S3 round trips of this one. The wait on the
     * oldest hand-off is the only place a slow S3 reaches the scrub, and it is what bounds memory.
     */
    private async handOff(): Promise<void> {
        if (this.outgoing.length === 0 && this.outgoingOffsets.size === 0) {
            return
        }
        const handoff: WriteHandoff = { images: this.outgoing, offsets: [...this.outgoingOffsets.values()] }
        this.outgoing = []
        this.outgoingBytes = 0
        this.outgoingOffsets = new Map()
        const write = this.writeLane(() => this.writeOrPoison(handoff))
        this.writesInFlight.push(write)
        const forget = (): void => {
            const index = this.writesInFlight.indexOf(write)
            if (index >= 0) {
                void this.writesInFlight.splice(index, 1)
            }
        }
        void write.then(forget, forget)
        if (this.writesInFlight.length >= MAX_WRITES_IN_FLIGHT) {
            const waitedFrom = performance.now()
            try {
                await this.writesInFlight[0]
            } finally {
                ImageScrubConsumerMetrics.observeWriteWait((performance.now() - waitedFrom) / 1000)
            }
        }
    }

    private async writeOrPoison(handoff: WriteHandoff): Promise<void> {
        if (this.writeFailure !== undefined) {
            throw this.writeFailure
        }
        // Found by the hand-off ahead of this one, whose offsets could not be stored: the span belongs
        // to another pod now, and writing it here would leave a second shard under a random key.
        if (this.partitionsRevoked) {
            logger.warn('🔁', 'image_scrub_handoff_discarded_after_revoke', {
                images: handoff.images.length,
                partitions: handoff.offsets.map((offset) => offset.partition),
            })
            ImageScrubConsumerMetrics.incOffsetsDiscarded(handoff.offsets.length)
            this.forgetUnwritten(handoff.images)
            return
        }
        const startedAt = performance.now()
        try {
            await this.write(handoff)
        } catch (error) {
            if (this.writeFailure === undefined) {
                this.writeFailure = error ?? new Error('image shard write failed')
            }
            ImageScrubConsumerMetrics.incBatchFailed('write')
            throw error
        }
        // Observed on success only, so an S3 incident's retry budgets do not read as slow writes.
        ImageScrubConsumerMetrics.observeWrite((performance.now() - startedAt) / 1000)
    }

    /** Retains nothing between batches, so unlike [[seenRefs]] this dedup cannot be sized wrong or disabled. */
    private planBatch(messages: Message[]): PlannedScrub[] {
        const planned: PlannedScrub[] = []
        const inlineRefs = new Set<string>()
        const urlLocationByRef = new Map<string, Pick<PlannedScrub, 'sourceTopic' | 'sourcePartition'>>()
        for (const [index, m] of messages.entries()) {
            const ref = m.key?.toString('utf8')
            // The ref's hash is a producer-side per-team HMAC; this consumer doesn't hold the key and
            // trusts the producer (the topic's only writer) that the key names these bytes.
            const parsed = ref ? parseImageRef(ref) : null
            if (!ref || !parsed || !m.value) {
                ImageScrubConsumerMetrics.incInvalidKey()
                continue
            }
            const headers = parseKafkaHeaders(m.headers)
            const allowedTransportHeaders =
                parsed.source === 'url'
                    ? [CONTENT_TYPE_HEADER, CONTENT_ENCODING_HEADER, CAPTURE_TIMESTAMP_HEADER, INGESTION_VERSION_HEADER]
                    : [CAPTURE_TIMESTAMP_HEADER, INGESTION_VERSION_HEADER]
            const transportHeaders = Object.fromEntries(
                allowedTransportHeaders
                    .filter((header) => headers[header] !== undefined)
                    .map((header) => [header, headers[header]])
            )
            const capturedAtMs = Number(transportHeaders[CAPTURE_TIMESTAMP_HEADER])
            const candidate: PlannedScrub = {
                index,
                ref,
                teamId: parsed.teamId,
                sessionMonth: parsed.sessionMonth,
                datasetVersion: parsed.version,
                pseudoTeam: parsed.pseudoTeam,
                hash: parsed.hash,
                source: parsed.source,
                value: m.value,
                transportHeaders,
                capturedAtMs: Number.isSafeInteger(capturedAtMs) && capturedAtMs > 0 ? capturedAtMs : undefined,
                sourceTopic: m.topic,
                sourcePartition: m.partition,
                sourceOffset: m.offset,
                replayCount: Number(headers[REPLAY_COUNT_HEADER] ?? 0) || 0,
            }
            if (parsed.source === 'url') {
                const existing = urlLocationByRef.get(ref)
                if (existing) {
                    if (
                        existing.sourceTopic !== candidate.sourceTopic ||
                        existing.sourcePartition !== candidate.sourcePartition
                    ) {
                        throw new Error(`URL image ref ${ref} arrived on more than one Kafka partition`)
                    }
                } else {
                    urlLocationByRef.set(ref, candidate)
                }
                planned.push(candidate)
                continue
            }
            if (inlineRefs.has(ref)) {
                ImageScrubConsumerMetrics.incDeduped('batch')
                continue
            }
            inlineRefs.add(ref)
            if (this.seenRefs.has(ref)) {
                ImageScrubConsumerMetrics.incDeduped('pod')
                continue
            }
            planned.push(candidate)
        }
        return planned
    }

    /** A ref that was marked seen but never persisted would be deduped away unwritten if its partition came back here. */
    private forgetUnwritten(images: ScrubbedRef[]): void {
        for (const { ref, source } of images) {
            if (source === 'bytes') {
                this.seenRefs.delete(ref)
            }
        }
    }

    private stageOutgoing(ready: ScrubbedRef): void {
        this.outgoing.push(ready)
        this.outgoingBytes += ready.image.bytes.length
    }

    private recordOffsets(messages: Message[]): void {
        for (const offset of findOffsetsToCommit(messages)) {
            this.outgoingOffsets.set(`${offset.topic}:${offset.partition}`, offset)
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
                (image): SettledScrub => ({
                    slot,
                    scrubbed: image ? { ref: p.ref, source: p.source, image, capturedAtMs: p.capturedAtMs } : null,
                }),
                (error): SettledScrub => ({ slot, scrubbed: null, error: error ?? new Error('scrub failed') })
            )
    }

    private async scrubOne(
        planned: PlannedScrub,
        signal: AbortSignal
    ): Promise<ScrubbedImage | ScrubbedUrlImage | null> {
        let input = planned.value
        if (planned.source === 'url') {
            try {
                input = await prepareFetchedImage(
                    input,
                    planned.transportHeaders[CONTENT_TYPE_HEADER],
                    planned.transportHeaders[CONTENT_ENCODING_HEADER]
                )
            } catch (error) {
                if (!(error instanceof InvalidImageTransportError)) {
                    throw error
                }
                this.rememberContentAddressedRef(planned)
                ImageScrubConsumerMetrics.incSkipped(error.reason)
                return null
            }
        }

        let bytes: Buffer | null
        try {
            bytes = await this.scrubClient.scrub(input, signal, planned.ref)
        } catch (error) {
            if (!(error instanceof ScrubPoisoned) || !this.deadLetters) {
                throw error
            }
            // Parked before the ref is marked and before the slot retires, so a failure to park
            // leaves the image exactly where it was: still unscrubbed, still uncommitted, still
            // waiting. Marking first would advance the offset over an image held nowhere.
            await this.parkUntilAccepted(planned, error, signal)
            logger.warn('☠️', 'image_scrub_dead_lettered', { ref: planned.ref, ...error.detail })
            this.rememberContentAddressedRef(planned)
            ImageScrubConsumerMetrics.incDeadLettered(error.detail.reason)
            return null
        }
        if (bytes === null) {
            // Null is a verdict on these bytes. Inline refs are content-addressed, so their later
            // copies cannot succeed. URL refs stay eligible because a recrawl can carry new bytes.
            this.rememberContentAddressedRef(planned)
            ImageScrubConsumerMetrics.incSkipped('sidecar_rejected')
            return null
        }
        ImageScrubConsumerMetrics.incScrubbed()
        if (planned.source === 'url') {
            return {
                teamId: planned.teamId,
                sessionMonth: planned.sessionMonth,
                datasetVersion: planned.datasetVersion,
                hash: planned.hash,
                bytes,
                sourcePartition: planned.sourcePartition,
                sourceOffset: planned.sourceOffset,
            }
        }
        return {
            sessionMonth: planned.sessionMonth,
            datasetVersion: planned.datasetVersion,
            teamId: planned.teamId,
            pseudoTeam: planned.pseudoTeam,
            hash: planned.hash,
            bytes,
        }
    }

    private rememberContentAddressedRef(planned: PlannedScrub): void {
        if (planned.source === 'bytes') {
            this.seenRefs.add(planned.ref)
        }
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
        await this.parkImageUntilAccepted(
            {
                ref: planned.ref,
                bytes: planned.encryptedValue ?? planned.value,
                headers: planned.transportHeaders,
                detail: {
                    ...poisoned.detail,
                    ...(planned.teamId ? { teamId: planned.teamId } : { pseudoTeam: planned.pseudoTeam }),
                    hash: planned.hash,
                    sourceTopic: planned.sourceTopic,
                    sourcePartition: planned.sourcePartition,
                    sourceOffset: planned.sourceOffset,
                    // Carried back out, or the count restarts on every pass and the cap that
                    // bounds replay round trips never binds.
                    [REPLAY_COUNT_HEADER]: planned.replayCount,
                },
            },
            signal
        )
    }

    private async parkImageUntilAccepted(
        image: Parameters<DeadLetterSink['park']>[0],
        signal: AbortSignal
    ): Promise<void> {
        for (let attempt = 0; ; attempt++) {
            if (signal.aborted) {
                throw new ScrubAborted('scrub batch aborted')
            }
            try {
                await this.deadLetters!.park(image)
                return
            } catch (error) {
                ImageScrubConsumerMetrics.incDeadLetterFailed()
                logger.error('☠️', 'image_scrub_dead_letter_failed', {
                    ref: image.ref,
                    bytes: image.bytes.length,
                    attempts: attempt + 1,
                    error: String(error),
                })
                try {
                    await waitForRetry(Math.min(30_000, 500 * 2 ** attempt), undefined, { signal, ref: false })
                } catch (retryError) {
                    if (signal.aborted) {
                        throw new ScrubAborted('scrub batch aborted')
                    }
                    throw retryError
                }
            }
        }
    }

    /** Staged results are counted so a slow slot holding back retirement still applies backpressure. */
    private overCapacity(stagedCount = 0, stagedBytes = 0): boolean {
        return (
            this.outgoing.length + stagedCount >= this.options.maxImages ||
            this.outgoingBytes + stagedBytes >= this.options.maxBytes
        )
    }

    private async write(handoff: WriteHandoff): Promise<void> {
        if (handoff.images.length > 0) {
            const imageKeys = this.keyManager
                ? await this.keyManager.reader.read(
                      handoff.images.flatMap(({ image }) =>
                          image.sessionMonth === undefined
                              ? []
                              : [imageKeyId(Number(image.teamId), image.sessionMonth!)]
                      )
                  )
                : new Map()
            const keyed = handoff.images.filter(
                ({ image }) =>
                    image.sessionMonth === undefined ||
                    imageKeys.has(tableKeyString(imageKeyId(Number(image.teamId), image.sessionMonth!)))
            )
            const inlineItems = keyed.filter(
                (item): item is ScrubbedRef & { image: ScrubbedImage } => item.source === 'bytes'
            )
            const urlItems = keyed.filter(
                (item): item is ScrubbedRef & { image: ScrubbedUrlImage } => item.source === 'url'
            )
            // URL images first: their keys are deterministic, so a failure here leaves nothing behind,
            // while a shard is written under a fresh key that a replay would duplicate.
            await settleAll(
                urlItems.map((item) =>
                    this.writeLimiter(async () => {
                        const outcome = await this.store.writeUrlImage(
                            item.image,
                            item.image.sessionMonth === undefined
                                ? undefined
                                : imageKeys.get(
                                      tableKeyString(imageKeyId(Number(item.image.teamId), item.image.sessionMonth!))
                                  )
                        )
                        if (outcome === 'created' && item.capturedAtMs !== undefined) {
                            ImageScrubConsumerMetrics.observeCaptureToS3('url', item.capturedAtMs, Date.now())
                        }
                    })
                )
            )
            const groups = new Map<string, typeof inlineItems>()
            for (const item of inlineItems) {
                const groupId =
                    item.image.sessionMonth === undefined
                        ? String(item.image.teamId !== undefined)
                        : `v${item.image.datasetVersion}:${item.image.teamId}:${item.image.sessionMonth}`
                const group = groups.get(groupId) ?? []
                group.push(item)
                groups.set(groupId, group)
            }
            await settleAll(
                [...groups.values()].map((items) =>
                    this.writeLimiter(async () => {
                        const { bytes } = await this.store.writeShard(
                            items.map((item) => item.image),
                            items[0].image.sessionMonth === undefined
                                ? undefined
                                : imageKeys.get(
                                      tableKeyString(
                                          imageKeyId(Number(items[0].image.teamId), items[0].image.sessionMonth!)
                                      )
                                  )
                        )
                        const storedAtMs = Date.now()
                        for (const item of items) {
                            if (item.capturedAtMs !== undefined) {
                                ImageScrubConsumerMetrics.observeCaptureToS3('inline', item.capturedAtMs, storedAtMs)
                            }
                        }
                        ImageScrubConsumerMetrics.observeShard(items.length, bytes)
                    })
                )
            )
        }
        if (handoff.offsets.length > 0) {
            this.storeOffsetsUnlessRevoked(handoff.offsets)
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
     *
     * The write lane runs while the loop keeps polling, so a revoke can also land while a hand-off
     * is still writing. Its offsets are discarded here and the new owner rescrubs that span, which
     * can cost MAX_WRITES_IN_FLIGHT hand-offs per pod per rebalance. That is the accepted price of
     * overlapping the writes, and incOffsetsDiscarded is where it shows.
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
