import { request } from 'node:http'

import { promiseRetry } from '~/common/utils/retries'

/** Sidecar 500 = undecodable input: permanent, so it must not be retried (promiseRetry treats it as non-retriable). */
class PermanentScrubReject extends Error {}

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

    /**
     * Scrub raw image bytes. Returns the scrubbed bytes, or `null` if the sidecar rejected the input as
     * undecodable (permanent — skip that image). Throws on transient failure (busy/network/timeout) after
     * retries, so the caller leaves the Kafka window uncommitted and it replays (at-least-once).
     */
    public async scrub(bytes: Buffer): Promise<Buffer | null> {
        try {
            return await promiseRetry(
                async () => {
                    const { status, body } = await this.post(bytes)
                    if (status === 200) {
                        return body
                    }
                    if (status === 500) {
                        throw new PermanentScrubReject(`sidecar rejected undecodable input`)
                    }
                    throw new Error(`sidecar responded ${status}`) // 503 busy / other: transient, retry
                },
                'image-scrub-sidecar',
                this.maxRetries,
                undefined,
                undefined,
                [PermanentScrubReject]
            )
        } catch (error) {
            if (error instanceof PermanentScrubReject) {
                return null
            }
            throw error
        }
    }

    private post(bytes: Buffer): Promise<{ status: number; body: Buffer }> {
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
            req.end(bytes)
        })
    }
}
