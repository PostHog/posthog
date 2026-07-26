import { request } from 'node:http'

import { logger } from '~/common/utils/logger'

import { ImageScrubConsumerMetrics } from './metrics'

/** The timeout's own message, matched on rather than duplicated, so the reason label cannot drift. */
const REQUEST_TIMED_OUT = 'scrub request timed out'

/** Why a single attempt did not come back with bytes, for the backpressure metric's label. */
export type ScrubWaitReason = 'busy' | 'timeout' | 'transport'

/** Raised only when the caller hangs up, which is the one condition that stops the wait. */
export class ScrubAborted extends Error {}

const BACKOFF_BASE_MS = 100
const BACKOFF_MAX_MS = 5_000

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
function backoffMs(attempt: number, random: () => number): number {
    return Math.round(random() * Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** attempt))
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
            try {
                const { status, body } = await this.post(bytes, signal)
                if (status === 200 && body.length > 0) {
                    return body
                }
                if (status === 422 || status === 413) {
                    return null
                }
                reason = status === 503 ? 'busy' : 'transport'
            } catch (error) {
                if (error instanceof ScrubAborted) {
                    throw error
                }
                // Refused, reset, or destroyed by the request timeout. None of them say anything
                // about this image, and none of them are fixed by dropping it.
                reason = (error as Error)?.message === REQUEST_TIMED_OUT ? 'timeout' : 'transport'
            }
            ImageScrubConsumerMetrics.incScrubWait(reason)
            if (attempt === STUCK_AFTER_ATTEMPTS) {
                ImageScrubConsumerMetrics.incStuckImage()
                logger.warn('🚨', 'image_scrub_image_stuck', {
                    ref,
                    reason,
                    attempts: attempt + 1,
                    bytes: bytes.length,
                })
            }
            await this.sleep(backoffMs(attempt, this.random))
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
