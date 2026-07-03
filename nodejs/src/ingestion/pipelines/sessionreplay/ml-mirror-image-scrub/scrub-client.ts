import { request } from 'node:http'

import { promiseRetry } from '~/common/utils/retries'

/** Sidecar 422/413 (undecodable or too large): a permanent input rejection, never retried. */
class PermanentScrubReject extends Error {}

class ScrubAborted extends Error {}

/**
 * Client for the image-scrub sidecar (a co-located container). Sends raw image bytes, gets scrubbed bytes.
 * Uses node:http (not the global fetch / external-request util): the call is to localhost, the response is
 * binary, and there's no untrusted-URL egress to guard.
 */
export class ScrubClient {
    private readonly url: URL

    constructor(
        baseUrl: string,
        private readonly timeoutMs: number,
        private readonly maxRetries: number
    ) {
        this.url = new URL('/scrub', baseUrl)
    }

    /** Scrubbed bytes, or null when the sidecar rejects the input as undecodable (422). Throws on transient
     *  failure or abort, so the caller can replay. */
    public async scrub(bytes: Buffer, signal?: AbortSignal): Promise<Buffer | null> {
        try {
            return await promiseRetry(
                async () => {
                    if (signal?.aborted) {
                        throw new ScrubAborted('scrub batch aborted')
                    }
                    const { status, body } = await this.post(bytes, signal)
                    if (status === 200) {
                        // An empty 200 would persist a zero-length image; treat it as transient so it replays.
                        if (body.length === 0) {
                            throw new Error('sidecar returned an empty 200 body')
                        }
                        return body
                    }
                    if (status === 422 || status === 413) {
                        throw new PermanentScrubReject(`sidecar rejected the input (${status})`)
                    }
                    throw new Error(`sidecar responded ${status}`) // 500 transient / 503 busy: retry
                },
                'image-scrub-sidecar',
                // promiseRetry's count is total attempts, so +1 makes maxRetries mean retries-after-the-first-try.
                this.maxRetries + 1,
                undefined,
                undefined,
                [PermanentScrubReject, ScrubAborted]
            )
        } catch (error) {
            if (error instanceof PermanentScrubReject) {
                return null
            }
            throw error
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
            req.setTimeout(this.timeoutMs, () => req.destroy(new Error('scrub request timed out')))
            req.on('error', reject)
            // Tear the request down if the batch is aborted (deadline hit) so we don't leak a socket mid-flush.
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
