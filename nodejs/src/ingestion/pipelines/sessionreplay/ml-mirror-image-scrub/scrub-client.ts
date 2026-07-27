import { request } from 'node:http'

import { logger } from '~/common/utils/logger'

import { ImageScrubConsumerMetrics } from './metrics'

/** The timeout's own message, matched on rather than duplicated, so the reason label cannot drift. */
const REQUEST_TIMED_OUT = 'scrub request timed out'

/**
 * Why a single attempt did not come back with bytes.
 *
 * `rejected` is kept apart from `transport` because only it means the sidecar took the image,
 * looked at it, and could not produce bytes. A refused or reset socket says nothing about content.
 */
export type ScrubWaitReason = 'busy' | 'timeout' | 'transport' | 'rejected'

/** Raised only when the caller hangs up, which is the one condition that stops the wait. */
export class ScrubAborted extends Error {}

/** A response no amount of waiting can turn into bytes, so the batch fails loudly instead. */
export class ScrubContractError extends Error {}

/**
 * This image, specifically, is one the sidecar cannot process. Its bytes belong in the dead-letter
 * topic so the partition can move on.
 */
export class ScrubPoisoned extends Error {
    constructor(
        message: string,
        readonly detail: { reason: ScrubWaitReason; lastError: string; attempts: number; waitedMs: number }
    ) {
        super(message)
    }
}

/**
 * What makes an image poison rather than unlucky.
 *
 * This is the whole safety question for the dead-letter path, because under saturation every image
 * waits a long time, so anything keyed on waiting alone would dead-letter the entire stream during a
 * backlog. That is the mass loss the wait exists to prevent, arriving through a different door.
 *
 * A poison image is distinguished by failing WHILE OTHER IMAGES SUCCEED. A sidecar that is full or
 * wedged fails everything equally, so no image ever meets the second condition and the lane keeps
 * waiting, which is correct. Only once the sidecar has demonstrably scrubbed other images can a
 * persistent failure be attributed to this one.
 *
 * A 503 is excluded from the count for the same reason: it is the sidecar declining to look at the
 * image at all, so it says nothing about the content, and under load an unlucky image can collect
 * plenty of them while its neighbours get slots.
 */
const POISON_MIN_FAILURES = 12

/**
 * Other images the sidecar must scrub while this one keeps being rejected.
 *
 * Deliberately small, and it must stay below the pod's scrub concurrency. A batch cannot finish
 * while one of its images is still in flight, and a pod cannot poll for more work until its batch
 * finishes, so the only successes that can ever arrive are from the handful of slots running
 * alongside this image right now. Ask for more than that and an image late in a batch can never
 * reach the threshold, the batch never returns, and the pod stops consuming for good: a deadlock
 * rather than the stall the dead-letter topic was added to remove. ImageBatcher asserts the
 * relationship at construction so a future concurrency change fails at boot instead of in traffic.
 */
export const POISON_MIN_OTHER_SUCCESSES = 3

/**
 * Accumulated backoff after which a sidecar that keeps answering is taken at its word.
 *
 * The success test cannot be satisfied when nothing else is succeeding, and the images in a batch
 * are chosen by whoever produced them: fill one with content the sidecar rejects and no peer is left
 * to prove it works, so the gate never opens. This is the way out. It only applies while the sidecar
 * is still returning considered answers, so a full or unreachable one still waits forever.
 *
 * It has to fire comfortably inside Kafka's max.poll.interval.ms (300s), and that is the binding
 * constraint rather than a preference. A batch cannot return while one of its images is in flight,
 * so a threshold above the lease can never be reached: the group fences the pod first, the partition
 * moves, and its new owner repeats the same work and is fenced in turn. The gate would be dead code
 * and the images would circle the fleet. This counts backoff only, and real elapsed time is longer,
 * so the margin below the lease has to be generous rather than exact.
 *
 * The trade is deliberate. A sidecar broken for this long parks images rather than holding them,
 * which keeps every byte, is loud in the dead-letter counter, and is replayable, against a silent
 * stall that holds a shared partition hostage and moves nothing.
 */
export const POISON_MAX_WAITED_MS = 120_000

const BACKOFF_BASE_MS = 100
/**
 * Ceilings on the wait, by what the failure says about the sidecar.
 *
 * A 503 is the sidecar stating it is full, so backing off hard is the point: at the short cap eight
 * in-flight images per pod keep up a steady stream of re-posts against something already shedding,
 * which is load rather than backpressure and slows the recovery it is waiting for. A refused socket
 * is different, because the ordinary cause is the sidecar still starting up in the same pod, and
 * waiting half a minute to notice it came up is a needless stall.
 */
const BACKOFF_MAX_MS: Record<ScrubWaitReason, number> = {
    busy: 30_000,
    timeout: 5_000,
    transport: 5_000,
    // The sidecar answered, so it is neither full nor unreachable, and re-asking quickly costs it a
    // whole scrub attempt each time. Backed off like a shed request rather than like a lost socket.
    rejected: 30_000,
}

/**
 * Backoff time on one image before it is called out by ref, and the interval between repeats.
 *
 * Measured in time rather than attempts because the per-reason caps differ by six times, so a fixed
 * attempt count means three minutes on the busy path and forty seconds on the others. Two minutes is
 * far longer than any healthy sidecar spends on one image, so crossing it means either a sidecar
 * that is down or an image it cannot process. The second is the one that needs naming: the bytes are
 * user-controlled, and an image that fails the same way forever holds the head of its partition,
 * which is a stall shared by every team whose records hash to it. Waiting still beats discarding,
 * but it must not be silent.
 *
 * Accumulated from the backoffs rather than read off a clock, so it measures time spent waiting on
 * the sidecar rather than time the process spent descheduled, and so tests can drive it.
 */
const STUCK_AFTER_WAITED_MS = 120_000

/** Full jitter, so a pod's eight in-flight images do not all re-post to a busy sidecar in lockstep. */
function backoffMs(attempt: number, reason: ScrubWaitReason, random: () => number): number {
    return Math.round(random() * Math.min(BACKOFF_MAX_MS[reason], BACKOFF_BASE_MS * 2 ** attempt))
}

/**
 * Whether waiting could ever change the answer.
 *
 * 5xx and the two "come back later" 4xx are the sidecar being unable to serve this image right now.
 * Any other status is the sidecar answering a question we did not think we were asking: a 404 from a
 * misdirected SIDECAR_URL or a renamed route, a 400 from a contract that has drifted. Waiting on
 * those forever converts a deploy-time mistake into a pod that consumes nothing, passes every probe,
 * and shows up only as lag, so they are raised instead.
 */
function isWaitable(status: number): boolean {
    return status >= 500 || status === 408 || status === 429
}

export class ScrubClient {
    private readonly url: URL
    /**
     * Images this pod has scrubbed, ever. Only ever read as a difference, to answer "has the sidecar
     * been working while this one image kept failing", which is what separates poison from load.
     */
    private successes = 0

    constructor(
        baseUrl: string,
        private readonly timeoutMs: number,
        /**
         * Whether a dead-letter destination exists. Without one there is nowhere to put a poison
         * image, and the only alternative to waiting would be discarding it, so the client keeps
         * waiting instead. Failing safe here means a misconfigured producer costs throughput on one
         * partition rather than data.
         */
        private readonly deadLetters: boolean = false,
        // unref'd: an abort stops the wait but leaves this timer scheduled, and a referenced one
        // holds the event loop open for the rest of its interval, which on the busy path is half a
        // minute of a process that has already finished shutting down.
        private readonly sleep: (ms: number) => Promise<void> = (ms) =>
            new Promise((resolve) => setTimeout(resolve, ms).unref()),
        private readonly random: () => number = Math.random
    ) {
        this.url = new URL('/scrub', baseUrl)
    }

    /**
     * Scrubbed bytes, or null when the sidecar permanently rejected the content (422/413).
     *
     * A sidecar with no capacity is waited on, not given up on, however long that takes. Kafka is
     * already holding this image durably, so the only thing a bounded retry buys is the chance to
     * throw away data the log was keeping safe; consuming more slowly costs nothing but lag, which
     * the topic exists to absorb. The wait is what applies backpressure: a batch that takes longer
     * calls consume() later, so the consumer paces itself to whatever the sidecar can execute,
     * without needing to pause partitions explicitly.
     *
     * Only two things end the loop. Bytes, or a verdict on the content that no retry could change.
     * The caller hanging up raises [[ScrubAborted]], which belongs to shutdown rather than to load.
     */
    public async scrub(bytes: Buffer, signal?: AbortSignal, ref?: string): Promise<Buffer | null> {
        let waitedMs = 0
        let stuckReports = 0
        let blamableFailures = 0
        const successesAtStart = this.successes
        for (let attempt = 0; ; attempt++) {
            if (signal?.aborted) {
                throw new ScrubAborted('scrub batch aborted')
            }
            let reason: ScrubWaitReason
            let detail: string
            try {
                const { status, body } = await this.post(bytes, signal)
                if (status === 200 && body.length > 0) {
                    this.successes += 1
                    return body
                }
                if (status === 422 || status === 413) {
                    return null
                }
                // An empty 200 is deliberately NOT a contract error: the sidecar's success path
                // returns whatever the scrub produced, so a zero-length result is reachable from
                // image content. Treating it as a deployment fault would let one image crash-loop
                // every pod, which is the failure this whole lane has been climbing out of.
                if (status !== 200 && !isWaitable(status)) {
                    throw new ScrubContractError(`sidecar responded ${status}, which no wait can change`)
                }
                reason = status === 503 ? 'busy' : 'rejected'
                detail = status === 200 ? 'sidecar returned an empty body' : `sidecar responded ${status}`
            } catch (error) {
                if (error instanceof ScrubAborted || error instanceof ScrubContractError) {
                    throw error
                }
                // Refused, reset, or destroyed by the request timeout. None of them say anything
                // about this image, and none of them are fixed by dropping it.
                detail = (error as Error)?.message ?? String(error)
                reason = detail === REQUEST_TIMED_OUT ? 'timeout' : 'transport'
            }
            if (signal?.aborted) {
                throw new ScrubAborted('scrub batch aborted')
            }
            ImageScrubConsumerMetrics.incScrubWait(reason)
            // Only a considered answer counts towards blaming the content. A 503 is the sidecar
            // declining to look at the image at all; a timeout is this caller giving up first, since
            // its budget is shorter than the sidecar's own job deadline, so an image that is merely
            // slow trips it while the sidecar is still working; and a refused or reset socket is the
            // sidecar being unreachable, which is true of every image at once.
            if (reason === 'rejected') {
                blamableFailures += 1
            }
            const sidecarProvenHealthy = this.successes - successesAtStart >= POISON_MIN_OTHER_SUCCESSES
            const waitedTooLong = waitedMs >= POISON_MAX_WAITED_MS
            if (
                this.deadLetters &&
                blamableFailures >= POISON_MIN_FAILURES &&
                (sidecarProvenHealthy || waitedTooLong)
            ) {
                throw new ScrubPoisoned(`sidecar cannot process this image: ${detail}`, {
                    reason,
                    lastError: detail,
                    attempts: attempt + 1,
                    waitedMs,
                })
            }
            const delayMs = backoffMs(attempt, reason, this.random)
            waitedMs += delayMs
            // Repeated rather than emitted once: a single increment lets a rate() alert fire and then
            // resolve itself while the partition is still stalled, which is the opposite of what a
            // head-of-line block should look like.
            if (waitedMs >= STUCK_AFTER_WAITED_MS * (stuckReports + 1)) {
                stuckReports += 1
                ImageScrubConsumerMetrics.incStuckImage()
                // The error text exists nowhere else: the caller sees a counter, and telling a
                // misdirected URL apart from genuine saturation needs the message, not the label.
                logger.warn('🚨', 'image_scrub_image_stuck', {
                    ref,
                    reason,
                    detail,
                    attempts: attempt + 1,
                    waitedMs,
                    bytes: bytes.length,
                })
            }
            await this.waitOrAbort(delayMs, signal)
        }
    }

    /** Sleeps, but gives the wait up the moment the caller hangs up rather than after the full backoff. */
    private async waitOrAbort(ms: number, signal?: AbortSignal): Promise<void> {
        if (!signal) {
            await this.sleep(ms)
            return
        }
        let release = (): void => {}
        const aborted = new Promise<void>((resolve) => {
            const onAbort = (): void => resolve()
            release = () => signal.removeEventListener('abort', onAbort)
            signal.addEventListener('abort', onAbort, { once: true })
        })
        try {
            await Promise.race([this.sleep(ms), aborted])
        } finally {
            release()
        }
        if (signal.aborted) {
            throw new ScrubAborted('scrub batch aborted')
        }
    }

    private post(bytes: Buffer, signal?: AbortSignal): Promise<{ status: number; body: Buffer }> {
        return new Promise((resolve, reject) => {
            const req = request(
                this.url,
                {
                    method: 'POST',
                    headers: { 'content-type': 'application/octet-stream', 'content-length': bytes.length },
                },
                (res) => {
                    const chunks: Buffer[] = []
                    res.on('data', (chunk: Buffer) => chunks.push(chunk))
                    res.on('end', () => resolve({ status: res.statusCode ?? 0, body: Buffer.concat(chunks) }))
                    res.on('error', reject)
                }
            )
            req.setTimeout(this.timeoutMs, () => req.destroy(new Error(REQUEST_TIMED_OUT)))
            req.on('error', reject)
            if (signal) {
                const onAbort = (): void => {
                    req.destroy(new ScrubAborted('scrub batch aborted'))
                }
                if (signal.aborted) {
                    onAbort()
                } else {
                    signal.addEventListener('abort', onAbort, { once: true })
                    req.on('close', () => signal.removeEventListener('abort', onAbort))
                }
            }
            req.end(bytes)
        })
    }
}
