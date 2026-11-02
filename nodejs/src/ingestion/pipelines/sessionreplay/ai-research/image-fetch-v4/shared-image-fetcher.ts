import { LRUCache } from 'lru-cache'
import { Counter } from 'prom-client'

import type { ImageFetchOptions, ImageFetchResult, ImageFetcher } from './image-fetcher'

const sharedFetches = new Counter({
    name: 'ai_research_v4_image_fetch_shared_fetches_total',
    help: 'v4 image fetches served by a recent fetch of the same URL in this process, with no request.',
})

const ENTRY_OVERHEAD_BYTES = 1024

/**
 * Serves one fetch of a URL to every job that asks for it within a short time. The v4 recorder sends one job per team
 * for the same URL and month, so without this each team costs the host a request. Only the plain bytes are shared, in
 * this process: the sink still seals each team's copy under that team's key.
 */
export class SharedImageFetcher implements ImageFetcher {
    private readonly recent: LRUCache<string, ImageFetchResult>
    private readonly inFlight = new Map<string, Promise<ImageFetchResult>>()

    constructor(
        private readonly inner: ImageFetcher,
        maxBytes = 64 * 1024 * 1024,
        lifetimeMs = 60_000,
        maxEntries = 4096
    ) {
        this.recent = new LRUCache({
            max: maxEntries,
            maxSize: maxBytes,
            // An origin can answer many URLs with empty images, so each entry also pays for its strings and headers.
            sizeCalculation: (result, id) =>
                (result.bytes?.length ?? 0) + 2 * (id.length + result.currentUrl.length) + ENTRY_OVERHEAD_BYTES,
            ttl: lifetimeMs,
            ttlAutopurge: true,
        })
    }

    public async fetch(url: string, options: ImageFetchOptions): Promise<ImageFetchResult> {
        // The TDM reservation decides if a response is refused, so only jobs with the same reservation share a response.
        const id = `${options.tdmrepReservation ? 'reserved' : 'open'} ${url}`
        const recent = this.recent.get(id)
        if (recent) {
            sharedFetches.inc()
            return recent
        }
        const pending = this.inFlight.get(id)
        if (pending) {
            const result = await pending
            if (isShareable(result)) {
                sharedFetches.inc()
                return result
            }
        }
        const own = this.inner.fetch(url, options)
        if (!this.inFlight.has(id)) {
            this.inFlight.set(id, own)
            const forget = (): void => {
                if (this.inFlight.get(id) === own) {
                    this.inFlight.delete(id)
                }
            }
            own.then(forget, forget)
        }
        const result = await own
        if (isShareable(result)) {
            this.recent.set(id, result)
        }
        return result
    }
}

/** A redirect depends on the hops a job has left, so only a direct image is shared. */
function isShareable(result: ImageFetchResult): boolean {
    return result.outcome === 'ok' && result.redirects === 0 && !!result.bytes
}
