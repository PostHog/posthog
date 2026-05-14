import { InternalApiClient, ResolvedRevision, logger } from '@posthog/agent-core'
import { LRUCache } from 'lru-cache'

export interface ResolverOptions {
    client: InternalApiClient
    ttlMs: number
    maxEntries?: number
}

/**
 * Resolves an inbound host (or explicit application id) to the live `(application, revision)`.
 *
 * Backed by an LRU keyed on the resolution input; entries expire after `ttlMs` so promotions
 * propagate without needing an explicit invalidation channel. The Django side will eventually
 * gain an admin invalidation endpoint, but TTL is enough for v1.
 */
export class RevisionResolver {
    private readonly cache: LRUCache<string, ResolvedRevision>

    constructor(private readonly options: ResolverOptions) {
        this.cache = new LRUCache({
            max: options.maxEntries ?? 5_000,
            ttl: options.ttlMs,
        })
    }

    async resolveDomain(domain: string): Promise<ResolvedRevision | null> {
        return this.lookup(`domain:${domain}`, () => this.options.client.resolve({ domain }))
    }

    async resolveApplication(applicationId: string): Promise<ResolvedRevision | null> {
        return this.lookup(`app:${applicationId}`, () => this.options.client.resolve({ applicationId }))
    }

    /** Manually evict a cache entry, used on promotion pings from Django. */
    invalidate(key: { domain?: string; applicationId?: string }): void {
        if (key.domain) {
            this.cache.delete(`domain:${key.domain}`)
        }
        if (key.applicationId) {
            this.cache.delete(`app:${key.applicationId}`)
        }
    }

    private async lookup(
        key: string,
        fetcher: () => Promise<ResolvedRevision | null>
    ): Promise<ResolvedRevision | null> {
        const cached = this.cache.get(key)
        if (cached) {
            return cached
        }
        try {
            const resolved = await fetcher()
            if (resolved) {
                this.cache.set(key, resolved)
            }
            return resolved
        } catch (err) {
            logger.error('RevisionResolver lookup failed', { key, error: String(err) })
            throw err
        }
    }
}
