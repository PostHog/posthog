import { request } from 'node:http'

import { promiseRetry } from '~/common/utils/retries'

class PermanentScrubReject extends Error {}

/** The timeout's own message, matched on rather than duplicated, so the reason label cannot drift. */
const REQUEST_TIMED_OUT = 'scrub request timed out'

/**
 * The sidecar had no capacity for this image: it shed the load, or it never answered inside the
 * request timeout, or the batch ran out of scrub budget while the image was queued.
 *
 * Separated from every other failure because the two need opposite handling: failing the batch over
 * a busy sidecar exits the consumer process, and the partitions it gives up land on pods that are
 * equally busy, so the saturation spreads rather than easing.
 *
 * The reasons blur into each other under load, which is why they are one class. The per-request
 * timeout is an inactivity timeout, so an image merely sitting in the sidecar's accept queue trips
 * it, and the retries queue behind the same jam.
 */
export type ScrubUnavailableReason = 'busy' | 'timeout' | 'transport' | 'aborted'

export class ScrubUnavailable extends Error {
    constructor(
        message: string,
        readonly reason: ScrubUnavailableReason,
        options?: ErrorOptions
    ) {
        super(message, options)
    }
}

class ScrubAborted extends ScrubUnavailable {
    constructor(message: string) {
        super(message, 'aborted')
    }
}

export class ScrubClient {
    private readonly url: URL

    constructor(
        baseUrl: string,
        private readonly timeoutMs: number,
        private readonly maxRetries: number
    ) {
        this.url = new URL('/scrub', baseUrl)
    }

    /**
     * Scrubbed bytes, or null when the sidecar permanently rejected the content (422/413).
     *
     * Anything else throws [[ScrubUnavailable]], and only that: every way the sidecar can fail to
     * return bytes is a fact about this one image plus the sidecar's current load, never a reason to
     * bring the consumer down. Keeping that guarantee at this boundary is what leaves the caller free
     * to lose a single image, since anything escaping it reaches the Kafka loop, which exits the
     * process on any error.
     */
    public async scrub(bytes: Buffer, signal?: AbortSignal): Promise<Buffer | null> {
        try {
            return await promiseRetry(
                async () => {
                    if (signal?.aborted) {
                        throw new ScrubAborted('scrub batch aborted')
                    }
                    const { status, body } = await this.post(bytes, signal)
                    if (status === 200) {
                        if (body.length === 0) {
                            throw new ScrubUnavailable('sidecar returned an empty 200 body', 'transport')
                        }
                        return body
                    }
                    if (status === 422 || status === 413) {
                        throw new PermanentScrubReject(`sidecar rejected the input (${status})`)
                    }
                    throw new ScrubUnavailable(`sidecar responded ${status}`, status === 503 ? 'busy' : 'transport')
                },
                'image-scrub-sidecar',
                // promiseRetry count is total attempts; +1 makes maxRetries mean retries after the first try.
                this.maxRetries + 1,
                undefined,
                undefined,
                [PermanentScrubReject, ScrubAborted]
            )
        } catch (error) {
            if (error instanceof PermanentScrubReject) {
                return null
            }
            if (error instanceof ScrubUnavailable) {
                throw error
            }
            // A transport error: the socket was refused, reset, or destroyed by the request timeout.
            // Restarting the consumer cannot fix any of them, since the sidecar is a separate
            // container that keeps running, so this is one lost image rather than a lost pod. The
            // original is kept as `cause`: this is the last place the real reason exists, and the
            // caller only records a counter.
            const message = error instanceof Error ? error.message : String(error)
            throw new ScrubUnavailable(message, message === REQUEST_TIMED_OUT ? 'timeout' : 'transport', {
                cause: error,
            })
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
