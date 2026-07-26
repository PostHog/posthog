import { request } from 'node:http'

import { logger } from '~/common/utils/logger'

import { ImageScrubConsumerMetrics } from './metrics'

/** The timeout's own message, matched on rather than duplicated, so the reason label cannot drift. */
const REQUEST_TIMED_OUT = 'scrub request timed out'

/** Why a single attempt did not come back with bytes, for the backpressure metric's label. */
export type ScrubWaitReason = 'busy' | 'timeout' | 'transport'

/** Raised only when the caller hangs up, which is the one condition that stops the wait. */
export class ScrubAborted extends Error {}

/** A response no amount of waiting can turn into bytes, so the batch fails loudly instead. */
export class ScrubContractError extends Error {}

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
const BACKOFF_MAX_MS: Record<ScrubWaitReason, number> = { busy: 30_000, timeout: 5_000, transport: 5_000 }

/** Attempts between repeats of the stuck signal, once the first has fired. */
const STUCK_REPEAT_ATTEMPTS = 20

/**
 * Attempts on one image before it is called out by ref.
 *
 * At the capped backoff this is a couple of minutes, which no healthy sidecar spends on a single
 * image, so crossing it means either a sidecar that is down or an image it cannot process. The
 * second is the one that needs naming: the bytes are user-controlled, and an image that fails the
 * same way forever holds the head of its partition, which is a stall shared by every team whose
 * records hash to it. Waiting is still better than discarding, but it must not be silent.
 */
const STUCK_AFTER_ATTEMPTS = 20

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

    constructor(
        baseUrl: string,
        private readonly timeoutMs: number,
        private readonly sleep: (ms: number) => Promise<void> = (ms) =>
            new Promise((resolve) => setTimeout(resolve, ms)),
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
        for (let attempt = 0; ; attempt++) {
            if (signal?.aborted) {
                throw new ScrubAborted('scrub batch aborted')
            }
            let reason: ScrubWaitReason
            let detail: string
            try {
                const { status, body } = await this.post(bytes, signal)
                if (status === 200 && body.length > 0) {
                    return body
                }
                if (status === 422 || status === 413) {
                    return null
                }
                if (!isWaitable(status)) {
                    throw new ScrubContractError(`sidecar responded ${status}, which no wait can change`)
                }
                reason = status === 503 ? 'busy' : 'transport'
                detail = `sidecar responded ${status}`
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
            // Repeated rather than emitted once: a single increment lets a rate() alert fire and then
            // resolve itself while the partition is still stalled, which is the opposite of what a
            // head-of-line block should look like.
            if (attempt >= STUCK_AFTER_ATTEMPTS && (attempt - STUCK_AFTER_ATTEMPTS) % STUCK_REPEAT_ATTEMPTS === 0) {
                ImageScrubConsumerMetrics.incStuckImage()
                // The error text exists nowhere else: the caller sees a counter, and telling a
                // misdirected URL apart from genuine saturation needs the message, not the label.
                logger.warn('🚨', 'image_scrub_image_stuck', {
                    ref,
                    reason,
                    detail,
                    attempts: attempt + 1,
                    bytes: bytes.length,
                })
            }
            await this.waitOrAbort(backoffMs(attempt, reason, this.random), signal)
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
